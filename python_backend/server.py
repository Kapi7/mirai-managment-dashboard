# server.py
from __future__ import annotations

from datetime import datetime, timedelta, date
from calendar import monthrange
import os
from typing import List, Optional, Dict, Any

import pytz
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# Core orchestration (already talks to Shopify, PayPal, Google, Meta, PSP)
from master_report_mirai import build_month_rows, _google_spend_usd
from meta_client import fetch_meta_insights_day


# ---------- Pydantic models ----------

class DateRangeRequest(BaseModel):
    """
    Request body for all date-range endpoints.
    Dates are inclusive and must be YYYY-MM-DD.
    """
    start_date: str
    end_date: str

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format")
        return v

    @property
    def start(self) -> date:
        return datetime.strptime(self.start_date, "%Y-%m-%d").date()

    @property
    def end(self) -> date:
        return datetime.strptime(self.end_date, "%Y-%m-%d").date()


# Pricing-specific models
class PriceUpdate(BaseModel):
    """Single price update"""
    variant_id: str
    new_price: float
    new_compare_at: Optional[float] = None
    compare_at_policy: str = "D"  # B, D, or Manual
    new_cogs: Optional[float] = None
    notes: str = ""
    item: str = ""
    current_price: float = 0.0


class ExecuteUpdatesRequest(BaseModel):
    """Request body for executing price updates"""
    updates: List[PriceUpdate]


class ProductAction(BaseModel):
    """Single product action (add or delete)"""
    action: str  # "add" or "delete"
    variant_id: str = ""
    title: str = ""
    price: float = 0.0
    sku: str = ""
    inventory: int = 0


class ProductActionsRequest(BaseModel):
    """Request body for product actions"""
    actions: List[ProductAction]


class CompetitorPriceCheckRequest(BaseModel):
    """Request body for competitor price check"""
    variant_ids: List[str]


class KorealySyncRequest(BaseModel):
    """Request body for syncing Korealy COGS to Shopify"""
    updates: List[Dict[str, Any]]  # List of {variant_id, new_cogs}


# ---------- FastAPI app ----------

app = FastAPI(title="Mirai Report API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",  # Allow all origins
        "https://mirai-managment-dashboard.onrender.com",
        "http://localhost:3001",
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Small helpers ----------

def _safe_shop_tz() -> str:
    """
    Resolve the Shopify/store timezone that all KPIs are based on.
    Falls back to UTC if env is wrong.
    """
    tz_name = (os.getenv("REPORT_TZ") or "UTC").strip()
    try:
        pytz.timezone(tz_name)
    except Exception:
        tz_name = "UTC"
    return tz_name


def _month_last(d: date) -> date:
    """Return the last day of the month for the given date."""
    last = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def _collect_kpis_range(start_date: date, end_date: date, shop_tz: str):
    """
    Call build_month_rows for each month touched by [start_date, end_date]
    and merge all KPIs into a single {date -> KPIs} dict.
    This is where Shopify + Meta + Google + PayPal + PSP are all combined.
    """
    all_kpis: dict[date, object] = {}

    # start from the 1st of the first month in the range
    cur = start_date.replace(day=1)

    while cur <= end_date:
        month_end = _month_last(cur)
        anchor = min(month_end, end_date)

        # build KPIs up to "anchor" within this month
        _, _, _, _, kpi_by_date = build_month_rows(anchor, shop_tz)

        # keep only the days that fall inside the requested range
        for d, k in kpi_by_date.items():
            if start_date <= d <= end_date:
                all_kpis[d] = k

        # move to first day of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    return all_kpis


# ---------- Health ----------

@app.get("/health")
async def health():
    return {"status": "ok", "message": "FastAPI is running"}


# ---------- NEW: Force backfill today orders (sends per-order messages) ----------

@app.post("/force-backfill-today")
async def force_backfill_today():
    """
    One-time operation:
    - Fetch all orders from "today" (store timezone)
    - Send per-order Telegram messages
    - Must be dedup-safe (so re-running doesn't spam)

    This endpoint expects monitor_orders.py to expose:
        backfill_today_and_send() -> int

    It should return number of order alerts sent.
    """
    try:
        # Import here (not at module import time) so server boot never fails
        # even if monitor file has optional deps or heavy imports.
        from monitor_orders import backfill_today_and_send  # type: ignore

        sent_count = backfill_today_and_send()
        return {"ok": True, "sent": int(sent_count)}

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import backfill_today_and_send from monitor_orders.py: {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Main daily report endpoint ----------

@app.post("/daily-report")
async def daily_report(req: DateRangeRequest):
    """
    Return one object per day in the range with full KPIs.

    Each object includes (per day):
      - date (YYYY-MM-DD)
      - label (human readable, e.g. "Mon, Nov 18")
      - orders, gross, discounts, refunds, net, cogs
      - shipping_charged, shipping_cost
      - google_spend, meta_spend, total_spend
      - google_pur, meta_pur, google_cpa, meta_cpa, general_cpa
      - psp_usd
      - operational_profit, net_margin, margin_pct
      - aov, returning_customers
    """
    try:
        if req.start > req.end:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        shop_tz = _safe_shop_tz()

        # Collect KPIs per calendar day across all relevant months
        kpis_by_date = _collect_kpis_range(req.start, req.end, shop_tz)

        data = []
        current = req.start
        while current <= req.end:
            k = kpis_by_date.get(current)
            if k is not None:
                # NOTE: k.* fields come from master_report_mirai.KPIs dataclass
                day_obj = {
                    "date": current.isoformat(),          # canonical date
                    "label": k.day,                       # pretty label from local_day_window
                    "orders": k.orders,
                    "gross": k.gross,
                    "discounts": k.discounts,
                    "refunds": k.refunds,
                    "net": k.net,
                    "cogs": k.cogs,
                    "shipping_charged": k.shipping_charged,
                    "shipping_cost": k.shipping_cost,
                    "google_spend": k.google_spend,
                    "meta_spend": k.meta_spend,
                    "total_spend": k.total_spend,
                    "google_pur": k.google_pur,
                    "meta_pur": k.meta_pur,
                    "google_cpa": k.google_cpa,
                    "meta_cpa": k.meta_cpa,
                    "general_cpa": k.general_cpa,
                    "psp_usd": k.psp_usd,
                    "operational_profit": k.operational,
                    "net_margin": k.margin,
                    "margin_pct": k.margin_pct,
                    "aov": k.aov,
                    "returning_customers": k.returning_count,
                }
                data.append(day_obj)

            current += timedelta(days=1)

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        # Safe fallback; helpful for debugging from Deno / Postman
        return {"error": str(e), "data": []}


# ---------- Debug endpoint: show orders for a specific day ----------

class DebugDayRequest(BaseModel):
    date: str  # YYYY-MM-DD


@app.post("/debug/day-orders")
async def debug_day_orders(req: DebugDayRequest):
    """
    Debug endpoint to show exactly which orders are counted for a specific day.
    Shows order names and their timestamps in both UTC and local (Nicosia) time.
    """
    try:
        from master_report_mirai import SHOPIFY_STORES, _parse_dt
        from shopify_client import fetch_orders_created_between_for_store

        shop_tz = _safe_shop_tz()
        tz = pytz.timezone(shop_tz)

        day = datetime.strptime(req.date, "%Y-%m-%d").date()
        start_local = tz.localize(datetime.combine(day, datetime.min.time()))
        end_local = tz.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))

        # Convert to UTC for display
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        orders_debug = []
        all_orders = []

        for store in SHOPIFY_STORES:
            domain = store["domain"]
            token = store["access_token"]

            # Fetch orders using the same method as the report
            created = fetch_orders_created_between_for_store(
                domain, token, start_local.isoformat(), end_local.isoformat(), exclude_cancelled=False
            )
            all_orders.extend(created)

        # Process each order
        in_window_count = 0
        for o in all_orders:
            dt = _parse_dt(o.get("createdAt"))
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_local = dt.astimezone(tz)

            in_window = start_local <= dt_local < end_local
            if in_window:
                in_window_count += 1

            is_cancelled = bool(o.get("cancelledAt"))

            orders_debug.append({
                "order_name": o.get("name"),
                "created_at_utc": o.get("createdAt"),
                "created_at_local": dt_local.isoformat(),
                "in_window": in_window,
                "is_cancelled": is_cancelled,
                "counted": in_window and not is_cancelled,
                "total_price": o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
            })

        # Sort by created time
        orders_debug.sort(key=lambda x: x["created_at_utc"] or "")

        return {
            "date": req.date,
            "timezone": shop_tz,
            "window": {
                "start_local": start_local.isoformat(),
                "end_local": end_local.isoformat(),
                "start_utc": start_utc.isoformat(),
                "end_utc": end_utc.isoformat(),
            },
            "orders_fetched": len(all_orders),
            "orders_in_window": in_window_count,
            "orders_counted": sum(1 for o in orders_debug if o["counted"]),
            "orders": orders_debug
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


# ---------- Supporting endpoint: raw ad spend only ----------

@app.post("/ad-spend")
async def ad_spend(req: DateRangeRequest):
    """
    Simple helper to fetch ad spend for a single day / short range.
    Still used by some tools; dashboard can rely on /daily-report instead.
    """
    try:
        if req.start > req.end:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        shop_tz = _safe_shop_tz()

        # Google Ads spend (helper expects single day + tz)
        google_spend = _google_spend_usd(req.start_date, shop_tz)

        # Meta Ads spend over the range (your meta_client already aligns by day)
        meta = fetch_meta_insights_day(req.start_date, req.end_date) or {}

        return {
            "google_spend": google_spend,
            "meta_spend": meta.get("meta_spend", 0.0),
            "meta_purchases": meta.get("meta_purchases", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "google_spend": 0.0,
            "meta_spend": 0.0,
            "meta_purchases": 0,
            "error": str(e),
        }


# ---------- Debug endpoint for Google Ads ----------

@app.get("/debug/google-ads")
async def debug_google_ads(day: str = None, clear_cache: bool = False):
    """
    Debug endpoint to test Google Ads spend fetch and see detailed logs.
    Usage: GET /debug/google-ads?day=2026-01-05&clear_cache=true
    """
    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    # Capture all print statements
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    shop_tz = _safe_shop_tz()
    test_day = day or datetime.now(pytz.timezone(shop_tz)).date().isoformat()

    result = {
        "test_day": test_day,
        "shop_tz": shop_tz,
        "cache_cleared": False,
        "google_spend": 0.0,
        "error": None,
        "logs": [],
    }

    try:
        # Clear cache if requested
        if clear_cache:
            from master_report_mirai import _GADS_CACHE
            cache_size = len(_GADS_CACHE)
            _GADS_CACHE.clear()
            result["cache_cleared"] = True
            result["cache_entries_cleared"] = cache_size

        # Capture output
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            spend = _google_spend_usd(test_day, shop_tz)
            result["google_spend"] = spend

        # Get captured logs
        stdout_val = stdout_capture.getvalue()
        stderr_val = stderr_capture.getvalue()

        if stdout_val:
            result["logs"].extend(stdout_val.strip().split('\n'))
        if stderr_val:
            result["logs"].extend(["STDERR: " + line for line in stderr_val.strip().split('\n')])

    except Exception as e:
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


@app.get("/debug/cache-status")
async def debug_cache_status():
    """
    Show current cache status for Google Ads spend.
    """
    from master_report_mirai import _GADS_CACHE

    cache_info = []
    for key, value in _GADS_CACHE.items():
        if isinstance(value, tuple):
            spend, timestamp = value
            age_minutes = (datetime.now() - timestamp).total_seconds() / 60
            cache_info.append({
                "key": key,
                "spend": f"${spend:.2f}",
                "age_minutes": round(age_minutes, 1),
                "cached_at": timestamp.isoformat(),
            })
        else:
            cache_info.append({
                "key": key,
                "value": value,
                "format": "old (float)"
            })

    return {
        "cache_entries": len(_GADS_CACHE),
        "cache_ttl_minutes": int(os.getenv("GOOGLE_ADS_CACHE_TTL_MINUTES", "30")),
        "entries": cache_info,
    }


# ---------- Pricing Endpoints ----------

# GET endpoints for data fetching
@app.get("/pricing/markets")
async def get_markets():
    """Get available markets"""
    try:
        from pricing_logic import get_available_markets
        markets = get_available_markets()
        return {"data": markets, "markets": markets}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/countries")
async def get_countries():
    """Get available countries for target pricing"""
    try:
        from pricing_logic import get_available_countries
        countries = get_available_countries()
        return {"data": countries, "countries": countries}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/items")
async def get_items(market: Optional[str] = None, use_cache: bool = True):
    """
    Get product variants from Shopify
    Optional market filter
    """
    try:
        from pricing_logic import fetch_items
        items = fetch_items(market_filter=market, use_cache=use_cache)
        return {"data": items, "items": items}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/price-updates")
async def get_price_updates():
    """Get pending price updates"""
    try:
        from pricing_logic import fetch_price_updates
        updates = fetch_price_updates()
        return {"data": updates, "updates": updates}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/update-log")
async def get_update_log(limit: Optional[int] = None):
    """Get price update history"""
    try:
        from pricing_logic import fetch_update_log
        log = fetch_update_log(limit=limit)
        return {"data": log, "log": log}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/target-prices")
async def get_target_prices(country: str = "US", use_cache: bool = True):
    """
    Calculate target prices based on Shopify data
    Returns calculated metrics for each variant
    """
    try:
        from pricing_logic import fetch_target_prices
        target_prices = fetch_target_prices(country_filter=country, use_cache=use_cache)
        return {"data": target_prices, "target_prices": target_prices}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# POST endpoints for actions
@app.post("/pricing/execute-updates")
async def execute_price_updates(req: ExecuteUpdatesRequest):
    """
    Execute price updates to Shopify

    Updates product variant prices based on the provided updates.
    Logs all changes to Google Sheets UpdatesLog.
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import execute_updates

        result = execute_updates(req.updates)

        return {
            "success": True,
            "updated_count": result["updated_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute price updates: {str(e)}"
        )


@app.post("/pricing/product-actions")
async def execute_product_actions(req: ProductActionsRequest):
    """
    Add or delete products from Shopify

    Executes batch product operations (add new products or delete existing ones).
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import execute_product_actions

        result = execute_product_actions(req.actions)

        return {
            "success": True,
            "added_count": result["added_count"],
            "deleted_count": result["deleted_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute product actions: {str(e)}"
        )


@app.post("/pricing/check-competitor-prices")
async def check_competitor_prices(req: CompetitorPriceCheckRequest):
    """
    Check competitor prices for specified variant IDs via SerpAPI

    This endpoint triggers a price scan using the smart filtering logic:
    - Trusted sellers only (excludes P2P marketplaces)
    - Outlier removal (median-based filtering)
    - Returns low/avg/high prices
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import check_competitor_prices

        result = check_competitor_prices(req.variant_ids)

        return {
            "success": True,
            "scanned_count": result["scanned_count"],
            "results": result["results"],
            "message": result["message"]
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check competitor prices: {str(e)}"
        )


@app.get("/pricing/korealy-reconciliation")
async def get_korealy_reconciliation():
    """
    Run Korealy reconciliation

    Fetches Korealy supplier prices from Google Sheets,
    compares with Shopify COGS, and returns mismatch analysis.
    """
    try:
        from korealy_reconciliation import run_reconciliation

        result = run_reconciliation()

        return {
            "success": result["success"],
            "results": result["results"],
            "stats": result["stats"],
            "message": result["message"]
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import korealy_reconciliation module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run Korealy reconciliation: {str(e)}"
        )


@app.post("/pricing/korealy-sync")
async def sync_korealy_to_shopify(req: KorealySyncRequest):
    """
    Sync selected Korealy COGS to Shopify

    Updates Shopify COGS with Korealy supplier prices for selected products.
    """
    try:
        from korealy_reconciliation import sync_korealy_to_shopify

        # Build variant_ids list and cogs_map from updates
        variant_ids = []
        korealy_cogs_map = {}

        for update in req.updates:
            variant_id = update.get("variant_id")
            new_cogs = update.get("new_cogs")

            if variant_id and new_cogs is not None:
                variant_ids.append(str(variant_id))
                korealy_cogs_map[str(variant_id)] = float(new_cogs)

        result = sync_korealy_to_shopify(variant_ids, korealy_cogs_map)

        return {
            "success": True,
            "updated_count": result["updated_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import korealy_reconciliation module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync Korealy COGS: {str(e)}"
        )


# ---------- Meta Ads Decision Engine ----------

from meta_decision_engine import create_engine, EngineConfig

class MetaAdsConfigRequest(BaseModel):
    """Configuration for decision engine"""
    target_cpa: Optional[float] = 18.50
    max_cpa: Optional[float] = 25.0
    min_ctr: Optional[float] = 0.8
    auto_pause_underperformers: Optional[bool] = False
    auto_scale_winners: Optional[bool] = False


# Helper to get marketing token
def _get_marketing_token():
    """Get Meta access token for marketing operations"""
    return os.getenv("META_ACCESS_TOKEN")


@app.get("/meta-ads/status")
async def meta_ads_quick_status(date_range: str = "today"):
    """
    Get quick campaign status overview

    Returns spend, clicks, CTR, conversions, CPA, health score
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        status = engine.get_quick_status(date_range)
        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.get("/meta-ads/analysis")
async def meta_ads_full_analysis(date_range: str = "today", campaign_id: str = None):
    """
    Run full campaign analysis with AI recommendations

    Returns metrics, decisions, alerts, and recommendations
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        report = engine.analyze_campaign(campaign_id, date_range)
        return report

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze: {str(e)}")


@app.get("/meta-ads/decisions")
async def meta_ads_get_decisions(date_range: str = "today"):
    """
    Get optimization decisions only

    Returns list of recommended actions (scale, pause, maintain)
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        report = engine.analyze_campaign(date_range=date_range)

        return {
            "timestamp": report["timestamp"],
            "health_score": report["health_score"],
            "decisions": report["decisions"],
            "alerts": report["alerts"],
            "recommendations": report["recommendations"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get decisions: {str(e)}")


@app.post("/meta-ads/execute-decision")
async def meta_ads_execute_decision(entity_id: str, action: str):
    """
    Execute a specific decision (pause/activate an ad/adset)

    Args:
        entity_id: The ad/adset/campaign ID
        action: PAUSE or ACTIVE
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        if action not in ["PAUSE", "ACTIVE", "PAUSED"]:
            raise HTTPException(status_code=400, detail="Action must be PAUSE or ACTIVE")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")
        result = client.update_status(entity_id, action.replace("PAUSE", "PAUSED"))

        return {"success": True, "entity_id": entity_id, "new_status": action}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute: {str(e)}")


@app.get("/meta-ads/campaigns")
async def meta_ads_get_campaigns():
    """
    Get all campaigns with their ad sets and ads
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        campaigns = client.get_campaigns()
        result = []

        for campaign in campaigns:
            campaign_data = {
                "id": campaign["id"],
                "name": campaign["name"],
                "status": campaign.get("effective_status"),
                "objective": campaign.get("objective"),
                "adsets": []
            }

            adsets = client.get_adsets(campaign["id"])
            for adset in adsets:
                adset_data = {
                    "id": adset["id"],
                    "name": adset["name"],
                    "status": adset.get("effective_status"),
                    "ads": []
                }

                ads = client.get_ads(adset["id"])
                for ad in ads:
                    adset_data["ads"].append({
                        "id": ad["id"],
                        "name": ad["name"],
                        "status": ad.get("effective_status")
                    })

                campaign_data["adsets"].append(adset_data)

            result.append(campaign_data)

        return {"campaigns": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get campaigns: {str(e)}")


# ---------- Meta Ads Campaign Creation Endpoints ----------

class CreateCampaignRequest(BaseModel):
    """Request body for creating a campaign"""
    name: str
    objective: str = "OUTCOME_SALES"  # OUTCOME_SALES, OUTCOME_LEADS, OUTCOME_AWARENESS
    status: str = "PAUSED"  # Start paused for safety


class CreateAdSetRequest(BaseModel):
    """Request body for creating an ad set"""
    campaign_id: str
    name: str
    daily_budget: int  # In cents (2500 = €25)
    targeting: Dict[str, Any]
    optimization_goal: str = "OFFSITE_CONVERSIONS"
    status: str = "PAUSED"


class CreateAdRequest(BaseModel):
    """Request body for creating an ad"""
    adset_id: str
    creative_id: str
    name: str
    status: str = "PAUSED"


class UpdateBudgetRequest(BaseModel):
    """Request body for updating ad set budget"""
    adset_id: str
    daily_budget: int  # In cents


@app.post("/meta-ads/campaigns/create")
async def meta_ads_create_campaign(req: CreateCampaignRequest):
    """
    Create a new Meta Ads campaign

    Default status is PAUSED for safety - activate manually after review.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_campaign(
            name=req.name,
            objective=req.objective,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "campaign_id": result.get("id"),
            "name": req.name,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create campaign: {str(e)}")


@app.post("/meta-ads/adsets/create")
async def meta_ads_create_adset(req: CreateAdSetRequest):
    """
    Create a new ad set within a campaign

    Targeting should include: age_min, age_max, genders, geo_locations, etc.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_adset(
            campaign_id=req.campaign_id,
            name=req.name,
            daily_budget=req.daily_budget,
            targeting=req.targeting,
            optimization_goal=req.optimization_goal,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "adset_id": result.get("id"),
            "name": req.name,
            "daily_budget": req.daily_budget,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ad set: {str(e)}")


@app.post("/meta-ads/ads/create")
async def meta_ads_create_ad(req: CreateAdRequest):
    """
    Create a new ad within an ad set

    Requires an existing creative_id from the account.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_ad(
            adset_id=req.adset_id,
            creative_id=req.creative_id,
            name=req.name,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "ad_id": result.get("id"),
            "name": req.name,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ad: {str(e)}")


@app.get("/meta-ads/creatives")
async def meta_ads_get_creatives(limit: int = 50):
    """
    Get available ad creatives from the account

    These can be used when creating new ads.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        creatives = client.get_creatives(limit=limit)

        return {
            "success": True,
            "count": len(creatives),
            "creatives": creatives
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get creatives: {str(e)}")


@app.get("/meta-ads/interests")
async def meta_ads_search_interests(q: str, limit: int = 20):
    """
    Search for targeting interests by keyword

    Use these interest IDs in ad set targeting.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        interests = client.get_targeting_interests(query=q, limit=limit)

        return {
            "success": True,
            "query": q,
            "count": len(interests),
            "interests": interests
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search interests: {str(e)}")


@app.get("/meta-ads/audiences")
async def meta_ads_get_audiences(limit: int = 50):
    """
    Get custom audiences (lookalikes, website visitors, etc.)

    These can be used for ad set targeting.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        audiences = client.get_custom_audiences(limit=limit)

        return {
            "success": True,
            "count": len(audiences),
            "audiences": audiences
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get audiences: {str(e)}")


@app.post("/meta-ads/budget")
async def meta_ads_update_budget(req: UpdateBudgetRequest):
    """
    Update an ad set's daily budget

    Budget is in cents (e.g., 2500 = €25)
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.update_budget(req.adset_id, req.daily_budget)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "adset_id": req.adset_id,
            "new_daily_budget": req.daily_budget
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update budget: {str(e)}")


@app.get("/meta-ads/targeting-presets")
async def meta_ads_get_targeting_presets():
    """
    Get pre-built targeting presets for common use cases
    """
    from meta_decision_engine import MetaAdsClient

    return {
        "presets": [
            {
                "name": "Mirai Skincare - Women US",
                "description": "Women 21-45 in US interested in skincare/beauty",
                "targeting": MetaAdsClient.build_skincare_targeting_preset()
            },
            {
                "name": "Broad - Women US 25-45",
                "description": "Broad targeting for women in US",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=25,
                    age_max=45,
                    genders=[1],
                    countries=["US"]
                )
            },
            {
                "name": "All Genders US 21-55",
                "description": "Wide audience in US",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=21,
                    age_max=55,
                    genders=[1, 2],
                    countries=["US"]
                )
            }
        ]
    }


# ---------- Local dev entrypoint ----------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
