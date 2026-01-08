"""
Simple FastAPI server for dashboard reports - NO automation, NO Telegram, NO complexity
Just: fetch data from APIs → calculate metrics → return JSON
"""
import os
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pytz

app = FastAPI(title="Mirai Reports API - Simple", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Log configuration on startup for debugging"""
    print("=" * 60)
    print("🚀 Mirai Reports API Starting Up")
    print("=" * 60)

    # Check for google-ads.yaml
    config_path = os.getenv("GOOGLE_ADS_CONFIG", "google-ads.yaml")
    config_locations = [
        config_path,
        "/app/google-ads.yaml",
        os.path.join(os.path.dirname(__file__), "google-ads.yaml")
    ]

    print("\n📋 Configuration Check:")
    print(f"  GOOGLE_ADS_CONFIG env: {os.getenv('GOOGLE_ADS_CONFIG', 'not set')}")
    print(f"  GOOGLE_ADS_CUSTOMER_IDS: {os.getenv('GOOGLE_ADS_CUSTOMER_IDS', 'not set')}")

    print("\n🔍 Looking for google-ads.yaml:")
    for loc in config_locations:
        exists = os.path.exists(loc)
        print(f"  {'✅' if exists else '❌'} {loc}")
        if exists:
            break

    print("\n" + "=" * 60)
    print()


class DateRangeRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@app.get("/health")
async def health():
    return {"status": "ok", "message": "Simple FastAPI is running"}


@app.post("/daily-report")
async def daily_report(req: DateRangeRequest):
    """
    Return daily metrics for the date range.
    This is a simplified version that will call the actual data fetching functions.
    """
    try:
        # Parse dates
        start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()

        if start_date > end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        # Import the actual data fetching logic
        # We'll use the existing modules but call them cleanly
        from report_logic import fetch_daily_reports

        data = fetch_daily_reports(start_date, end_date)

        return {"data": data}

    except ImportError as e:
        # If report_logic doesn't exist yet, return mock data
        return {
            "data": [
                {
                    "date": req.start_date,
                    "label": "Mock Data",
                    "orders": 10,
                    "gross": 1000.0,
                    "discounts": 50.0,
                    "refunds": 0.0,
                    "net": 950.0,
                    "cogs": 300.0,
                    "shipping_charged": 100.0,
                    "shipping_cost": 50.0,
                    "google_spend": 100.0,
                    "meta_spend": 50.0,
                    "total_spend": 150.0,
                    "google_pur": 5,
                    "meta_pur": 3,
                    "google_cpa": 20.0,
                    "meta_cpa": 16.67,
                    "general_cpa": 18.75,
                    "psp_usd": 25.0,
                    "operational_profit": 425.0,
                    "net_margin": 425.0,
                    "margin_pct": 44.74,
                    "aov": 95.0,
                    "returning_customers": 2
                }
            ]
        }
    except Exception as e:
        return {"error": str(e), "data": []}


# ==================== PRICING ENDPOINTS ====================

@app.get("/pricing/items")
async def get_items(market: str = None):
    """
    Get items list with optional market filter
    Query param: ?market=US
    """
    try:
        from pricing_logic import fetch_items
        data = fetch_items(market_filter=market)
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/pricing/price-updates")
async def get_price_updates():
    """
    Get pending price updates from PriceUpdates tab
    """
    try:
        from pricing_logic import fetch_price_updates
        data = fetch_price_updates()
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/pricing/update-log")
async def get_update_log(limit: int = 100):
    """
    Get price update history from UpdatesLog tab
    Query param: ?limit=50
    """
    try:
        from pricing_logic import fetch_update_log
        data = fetch_update_log(limit=limit)
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/pricing/target-prices")
async def get_target_prices(country: str = "US"):
    """
    Get target prices with optional country filter
    Query param: ?country=US
    """
    try:
        from pricing_logic import fetch_target_prices
        data = fetch_target_prices(country_filter=country)
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/pricing/markets")
async def get_markets():
    """
    Get list of available markets
    """
    try:
        from pricing_logic import get_available_markets
        markets = get_available_markets()
        return {"markets": markets}
    except Exception as e:
        return {"error": str(e), "markets": []}


@app.get("/pricing/countries")
async def get_countries():
    """
    Get list of available countries for target pricing
    """
    try:
        from pricing_logic import get_available_countries
        countries = get_available_countries()
        return {"countries": countries}
    except Exception as e:
        return {"error": str(e), "countries": ["US", "UK", "AU", "CA"]}


# Pydantic models for POST endpoints
class PriceUpdate(BaseModel):
    """Single price update"""
    variant_id: str
    new_price: float
    new_compare_at: Optional[float] = None
    compare_at_policy: str = "D"
    new_cogs: Optional[float] = None
    notes: str = ""
    item: str = ""
    current_price: float = 0.0


class ExecuteUpdatesRequest(BaseModel):
    """Request body for executing price updates"""
    updates: List[PriceUpdate]


class CompetitorPriceCheckRequest(BaseModel):
    """Request body for competitor price check"""
    variant_ids: List[str]


class KorealySyncRequest(BaseModel):
    """Request body for syncing Korealy COGS to Shopify"""
    updates: List[Dict[str, Any]]


# POST endpoints for pricing actions
@app.post("/pricing/execute-updates")
async def execute_price_updates(req: ExecuteUpdatesRequest):
    """
    Execute price updates to Shopify
    """
    try:
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
        raise HTTPException(status_code=500, detail=f"Could not import pricing_execution module: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute price updates: {str(e)}")


@app.post("/pricing/check-competitor-prices")
async def check_competitor_prices(req: CompetitorPriceCheckRequest):
    """
    Check competitor prices via SerpAPI
    """
    try:
        from pricing_execution import check_competitor_prices as check_prices
        result = check_prices(req.variant_ids)
        return {
            "success": True,
            "scanned_count": result["scanned_count"],
            "results": result["results"],
            "message": result["message"]
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_execution module: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check competitor prices: {str(e)}")


@app.get("/pricing/korealy-reconciliation")
async def get_korealy_reconciliation():
    """
    Run Korealy reconciliation
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
        raise HTTPException(status_code=500, detail=f"Could not import korealy_reconciliation module: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run Korealy reconciliation: {str(e)}")


@app.post("/pricing/korealy-sync")
async def sync_korealy_to_shopify(req: KorealySyncRequest):
    """
    Sync selected Korealy COGS to Shopify
    """
    try:
        from korealy_reconciliation import sync_korealy_to_shopify as sync_cogs

        # Build variant_ids list and cogs_map from updates
        variant_ids = []
        korealy_cogs_map = {}

        for update in req.updates:
            variant_id = update.get("variant_id")
            new_cogs = update.get("new_cogs")

            if variant_id and new_cogs is not None:
                variant_ids.append(str(variant_id))
                korealy_cogs_map[str(variant_id)] = float(new_cogs)

        result = sync_cogs(variant_ids, korealy_cogs_map)

        return {
            "success": True,
            "updated_count": result["updated_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import korealy_reconciliation module: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync Korealy COGS: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("simple_server:app", host="0.0.0.0", port=port, reload=False)
