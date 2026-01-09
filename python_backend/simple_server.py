"""
Simple FastAPI server for dashboard reports - NO automation, NO Telegram, NO complexity
Just: fetch data from APIs → calculate metrics → return JSON

Supports PostgreSQL database with fallback to real-time API calls
"""
import os
import uuid
import asyncio
import threading
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pytz

# Database service import (with graceful fallback)
try:
    from database.service import db_service
    DB_SERVICE_AVAILABLE = True
    print("✅ Database service imported successfully")
except ImportError as e:
    DB_SERVICE_AVAILABLE = False
    db_service = None
    print(f"⚠️ Database service import failed: {e}")

app = FastAPI(title="Mirai Reports API - Simple", version="2.0.0")

# ==================== BACKGROUND TASK TRACKING ====================
# In-memory store for background task progress
_BACKGROUND_TASKS: Dict[str, Dict[str, Any]] = {}


def _run_price_update_background(task_id: str, updates: List[Dict[str, Any]]):
    """Run price updates in background thread with progress tracking"""
    import time
    import requests

    task = _BACKGROUND_TASKS[task_id]
    task["status"] = "running"
    task["started_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
        SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
        SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

        results = []
        total = len(updates)
        updated_count = 0
        failed_count = 0

        for idx, update in enumerate(updates):
            task["progress"] = idx
            task["current_item"] = update.get("item", f"Variant {update.get('variant_id', '?')}")

            try:
                variant_id = update.get("variant_id")
                new_price = float(update.get("new_price", 0))
                policy = update.get("compare_at_policy", "D")
                item_name = update.get("item", "")

                variant_gid = f"gid://shopify/ProductVariant/{variant_id}"
                url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
                headers = {
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": SHOPIFY_TOKEN
                }

                # Get product ID and current prices
                query = """
                query($id: ID!) {
                    productVariant(id: $id) {
                        price
                        compareAtPrice
                        product { id }
                    }
                }
                """
                response = requests.post(url, json={"query": query, "variables": {"id": variant_gid}}, headers=headers, timeout=30)
                data = response.json()
                variant = data["data"]["productVariant"]
                product_id = variant["product"]["id"]
                current_price = float(variant["price"]) if variant["price"] else 0.0
                current_compare_at = float(variant["compareAtPrice"]) if variant["compareAtPrice"] else 0.0

                # Calculate compare_at based on policy
                if policy == "B":
                    new_compare_at = new_price
                elif policy == "D" and current_compare_at > 0 and current_price > 0:
                    discount_pct = (current_compare_at - current_price) / current_compare_at
                    new_compare_at = new_price / (1 - discount_pct) if discount_pct < 1 else new_price
                else:
                    new_compare_at = None

                # Update price
                mutation = """
                mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
                    productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                        productVariants { id price compareAtPrice }
                        userErrors { field message }
                    }
                }
                """
                variant_input = {"id": variant_gid, "price": str(new_price)}
                if new_compare_at is not None:
                    variant_input["compareAtPrice"] = str(new_compare_at)

                result = requests.post(url, json={
                    "query": mutation,
                    "variables": {"productId": product_id, "variants": [variant_input]}
                }, headers=headers, timeout=30)
                result_data = result.json()

                user_errors = result_data.get("data", {}).get("productVariantsBulkUpdate", {}).get("userErrors", [])
                if user_errors:
                    raise RuntimeError("; ".join([e["message"] for e in user_errors]))

                # Log the update
                from pricing_logic import log_price_update
                log_price_update(
                    variant_id=variant_id,
                    item=item_name,
                    old_price=current_price,
                    new_price=new_price,
                    old_compare_at=current_compare_at,
                    new_compare_at=new_compare_at or 0.0,
                    status="success",
                    notes=update.get("notes", "")
                )

                # Update database immediately
                if DB_SERVICE_AVAILABLE and db_service.is_available():
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(db_service.update_variant_price(
                            variant_id=variant_id,
                            price=new_price,
                            compare_at_price=new_compare_at
                        ))
                        loop.close()
                    except Exception as db_err:
                        print(f"⚠️ DB update failed for {variant_id}: {db_err}")

                updated_count += 1
                results.append({
                    "variant_id": variant_id,
                    "status": "success",
                    "message": f"Updated to ${new_price:.2f}"
                })

                time.sleep(0.1)

            except Exception as e:
                failed_count += 1
                results.append({
                    "variant_id": update.get("variant_id"),
                    "status": "failed",
                    "message": str(e)
                })

        task["status"] = "completed"
        task["progress"] = total
        task["results"] = results
        task["updated_count"] = updated_count
        task["failed_count"] = failed_count
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        task["message"] = f"Updated {updated_count} of {total} variants"

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"


def _run_competitor_scan_background(task_id: str, variant_ids: List[str]):
    """Run competitor price scan in background thread with progress tracking"""
    import time
    import requests

    task = _BACKGROUND_TASKS[task_id]
    task["status"] = "running"
    task["started_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        from smart_pricing import analyze_competitor_prices
        from pricing_logic import update_competitor_data, log_competitor_scan

        SERPAPI_KEY = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")
        SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
        SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
        SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

        if not SERPAPI_KEY:
            task["status"] = "failed"
            task["error"] = "SerpAPI key not configured"
            return

        results = []
        total = len(variant_ids)

        for idx, variant_id in enumerate(variant_ids):
            task["progress"] = idx
            task["current_item"] = variant_id

            try:
                variant_gid = f"gid://shopify/ProductVariant/{variant_id}"

                # Get product details from Shopify
                url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
                headers = {
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": SHOPIFY_TOKEN
                }

                query = """
                query($id: ID!) {
                    productVariant(id: $id) {
                        id
                        title
                        sku
                        price
                        compareAtPrice
                        product { title }
                        inventoryItem { unitCost { amount } }
                    }
                }
                """

                response = requests.post(url, json={"query": query, "variables": {"id": variant_gid}}, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")

                variant = data["data"]["productVariant"]
                product_title = variant["product"]["title"]
                variant_title = variant["title"]
                sku = variant["sku"]
                current_price = float(variant["price"]) if variant["price"] else 0.0
                compare_at = float(variant["compareAtPrice"]) if variant["compareAtPrice"] else 0.0
                cogs = 0.0
                if variant.get("inventoryItem") and variant["inventoryItem"].get("unitCost"):
                    cogs = float(variant["inventoryItem"]["unitCost"]["amount"])

                # Build search query
                search_query = f"{product_title} {variant_title}"
                if sku:
                    search_query += f" {sku}"

                task["current_item"] = f"{product_title} - {variant_title}"

                # Call SerpAPI
                serp_params = {
                    "engine": "google_shopping",
                    "q": search_query,
                    "gl": "us",
                    "hl": "en",
                    "num": 100,
                    "api_key": SERPAPI_KEY
                }

                serp_response = requests.get("https://serpapi.com/search.json", params=serp_params, timeout=60)
                serp_response.raise_for_status()
                serp_data = serp_response.json()

                # Extract prices
                competitor_prices = []
                seller_counts = {}

                for item in serp_data.get("shopping_results", []):
                    price_str = item.get("extracted_price")
                    seller = item.get("source", "Unknown")
                    if price_str:
                        competitor_prices.append({
                            "price": float(price_str),
                            "seller": seller,
                            "title": item.get("title", ""),
                            "link": item.get("link", ""),
                        })
                        seller_counts[seller] = seller_counts.get(seller, 0) + 1

                # Apply smart filtering
                analysis = analyze_competitor_prices(competitor_prices)
                top_sellers = sorted(seller_counts.items(), key=lambda x: x[1], reverse=True)[:5]

                # Calculate competitive price
                competitive_price = 0.0
                comp_note = "N/A"
                if analysis["comp_avg"] and analysis["comp_avg"] > 0:
                    min_margin = 0.25
                    min_price = cogs * (1 + min_margin) if cogs > 0 else 0
                    target_competitive = analysis["comp_avg"] * 0.97

                    if target_competitive >= min_price:
                        competitive_price = round(target_competitive, 2)
                        comp_note = "3% below avg"
                    elif min_price > 0:
                        competitive_price = round(min_price, 2)
                        comp_note = "Floor (25% margin)"

                # Store competitor data
                scan_data = {
                    "comp_low": analysis["comp_low"],
                    "comp_avg": analysis["comp_avg"],
                    "comp_high": analysis["comp_high"],
                    "raw_count": analysis["raw_count"],
                    "trusted_count": analysis["trusted_count"],
                    "filtered_count": analysis["filtered_count"],
                    "competitive_price": competitive_price,
                    "top_sellers": top_sellers,
                }
                update_competitor_data(variant_id, scan_data)

                # Log scan to history
                item_name = f"{product_title} - {variant_title}"
                log_competitor_scan(variant_id, item_name, scan_data)

                results.append({
                    "variant_id": variant_id,
                    "product_name": item_name,
                    "sku": sku,
                    "current_price": current_price,
                    "comp_avg": analysis["comp_avg"],
                    "competitive_price": competitive_price,
                    "status": "success"
                })

                time.sleep(0.6)  # Rate limiting

            except Exception as e:
                results.append({
                    "variant_id": variant_id,
                    "status": "failed",
                    "error": str(e)
                })

        task["status"] = "completed"
        task["progress"] = total
        task["results"] = results
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        task["message"] = f"Scanned {len([r for r in results if r.get('status') == 'success'])} of {total} variants"

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"


def _run_korealy_sync_background(task_id: str, variant_ids: List[str], korealy_cogs_map: Dict[str, float]):
    """Run Korealy COGS sync in background thread with progress tracking"""
    import time

    task = _BACKGROUND_TASKS[task_id]
    task["status"] = "running"
    task["started_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        from korealy_reconciliation import _shopify_graphql
        from pricing_logic import log_price_update

        results = []
        total = len(variant_ids)
        updated_count = 0
        failed_count = 0
        skipped_count = 0

        for idx, variant_id in enumerate(variant_ids):
            task["progress"] = idx
            task["current_item"] = f"Variant {variant_id}"

            if variant_id not in korealy_cogs_map:
                failed_count += 1
                results.append({
                    "variant_id": variant_id,
                    "status": "failed",
                    "message": "No Korealy COGS provided"
                })
                continue

            try:
                variant_gid = f"gid://shopify/ProductVariant/{variant_id}"
                new_cogs = float(korealy_cogs_map[variant_id])

                # Get inventory item ID and current COGS
                inv_query = """
                query($id: ID!) {
                    productVariant(id: $id) {
                        title
                        product { title }
                        inventoryItem {
                            id
                            unitCost {
                                amount
                                currencyCode
                            }
                        }
                    }
                }
                """
                inv_result = _shopify_graphql(inv_query, {"id": variant_gid})

                if not inv_result.get("data", {}).get("productVariant"):
                    raise RuntimeError(f"Variant not found")

                variant_data = inv_result["data"]["productVariant"]
                if not variant_data.get("inventoryItem"):
                    raise RuntimeError(f"No inventory item found")

                inv_item_id = variant_data["inventoryItem"]["id"]

                # Get current COGS
                old_cogs = 0.0
                if variant_data["inventoryItem"].get("unitCost"):
                    old_cogs = float(variant_data["inventoryItem"]["unitCost"]["amount"] or 0)

                product_title = variant_data["product"]["title"]
                variant_title = variant_data["title"]
                item_name = f"{product_title} — {variant_title}".strip(" — ")

                task["current_item"] = item_name

                # Skip if COGS already matches
                if abs(old_cogs - new_cogs) < 0.01:
                    skipped_count += 1
                    results.append({
                        "variant_id": variant_id,
                        "item": item_name,
                        "status": "skipped",
                        "message": f"COGS already ${new_cogs:.2f}"
                    })
                    continue

                # Update unit cost
                cost_mutation = """
                mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
                    inventoryItemUpdate(id: $id, input: $input) {
                        inventoryItem {
                            id
                            unitCost { amount currencyCode }
                        }
                        userErrors { field message }
                    }
                }
                """
                cost_result = _shopify_graphql(cost_mutation, {
                    "id": inv_item_id,
                    "input": {"cost": new_cogs}
                })

                cost_errors = cost_result.get("data", {}).get("inventoryItemUpdate", {}).get("userErrors", [])
                if cost_errors:
                    error_msgs = "; ".join([e.get("message", str(e)) for e in cost_errors])
                    raise RuntimeError(f"Shopify errors: {error_msgs}")

                # Log the update
                log_price_update(
                    variant_id=variant_id,
                    item=item_name,
                    old_price=old_cogs,
                    new_price=new_cogs,
                    old_compare_at=0.0,
                    new_compare_at=0.0,
                    status="success",
                    notes=f"KOREALY_COGS|{old_cogs:.2f}|{new_cogs:.2f}"
                )

                # Update database immediately
                if DB_SERVICE_AVAILABLE and db_service.is_available():
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(db_service.update_variant_price(
                            variant_id=variant_id,
                            cogs=new_cogs
                        ))
                        loop.close()
                    except Exception as db_err:
                        print(f"⚠️ DB update failed for {variant_id}: {db_err}")

                updated_count += 1
                results.append({
                    "variant_id": variant_id,
                    "item": item_name,
                    "status": "success",
                    "old_cogs": old_cogs,
                    "new_cogs": new_cogs,
                    "message": f"Updated ${old_cogs:.2f} → ${new_cogs:.2f}"
                })

                time.sleep(0.15)  # Rate limiting

            except Exception as e:
                failed_count += 1
                results.append({
                    "variant_id": variant_id,
                    "status": "failed",
                    "message": str(e)
                })

        task["status"] = "completed"
        task["progress"] = total
        task["results"] = results
        task["updated_count"] = updated_count
        task["failed_count"] = failed_count
        task["skipped_count"] = skipped_count
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        task["message"] = f"Updated {updated_count}, skipped {skipped_count}, failed {failed_count}"

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"


# CORS - read allowed origins from environment
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
if CORS_ORIGINS == "*":
    origins = ["*"]
else:
    origins = [origin.strip() for origin in CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

    # Check data persistence
    print("\n💾 Data Persistence:")
    render_disk = os.getenv("RENDER_DISK_PATH", "not set")
    print(f"  RENDER_DISK_PATH: {render_disk}")

    # Check if pricing_logic has loaded any data
    try:
        from pricing_logic import _COMPETITOR_DATA, _UPDATE_LOG, _DATA_DIR
        print(f"  Data directory: {_DATA_DIR}")
        print(f"  Competitor data loaded: {len(_COMPETITOR_DATA)} variants")
        print(f"  Update log loaded: {len(_UPDATE_LOG)} entries")
    except Exception as e:
        print(f"  ⚠️ Could not check pricing data: {e}")

    # Database status
    print("\n🗄️ Database Status:")
    if DB_SERVICE_AVAILABLE:
        if db_service.is_available():
            print("  ✅ Database configured and available")
            print("  📊 Data will be served from database (with API fallback)")
        else:
            print("  ⚠️ Database service loaded but DATABASE_URL not configured")
            print("  📊 Data will be served from real-time API calls")
    else:
        print("  ⚠️ Database service not available (import error)")
        print("  📊 Data will be served from real-time API calls")

    print("\n" + "=" * 60)
    print()


class DateRangeRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@app.get("/health")
async def health():
    return {"status": "ok", "message": "Simple FastAPI is running"}


@app.get("/db-status")
async def db_status():
    """
    Check database connection status
    """
    if not DB_SERVICE_AVAILABLE:
        return {
            "available": False,
            "configured": False,
            "message": "Database service not installed"
        }

    if not db_service.is_available():
        return {
            "available": False,
            "configured": False,
            "message": "DATABASE_URL not configured"
        }

    # Try to check connection
    try:
        from database.connection import check_db_connection
        is_connected = await check_db_connection()
        return {
            "available": is_connected,
            "configured": True,
            "message": "Database connected" if is_connected else "Database connection failed"
        }
    except Exception as e:
        return {
            "available": False,
            "configured": True,
            "message": f"Connection check failed: {e}"
        }


@app.get("/db-stats")
async def db_stats():
    """
    Get database statistics - orders, products, variants count
    """
    if not DB_SERVICE_AVAILABLE:
        # Try to get more info about why import failed
        import subprocess
        try:
            result = subprocess.run(['pip', 'list'], capture_output=True, text=True)
            packages = result.stdout
            has_sqlalchemy = 'sqlalchemy' in packages.lower()
            has_asyncpg = 'asyncpg' in packages.lower()
        except:
            has_sqlalchemy = False
            has_asyncpg = False
            packages = "Could not get package list"

        return {
            "error": "Database service not installed",
            "has_sqlalchemy": has_sqlalchemy,
            "has_asyncpg": has_asyncpg,
            "debug": "Check deploy logs for import error details"
        }

    try:
        stats = await db_service.get_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.post("/daily-report")
async def daily_report(req: DateRangeRequest):
    """
    Return daily metrics for the date range.
    Tries database first, falls back to real-time API calls.
    """
    try:
        # Parse dates
        start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()

        print(f"📋 Daily report request: {start_date} to {end_date}")

        if start_date > end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        # Try database first
        if DB_SERVICE_AVAILABLE and db_service.is_available():
            print(f"  📊 Trying database query...")
            try:
                db_data = await db_service.get_daily_kpis(start_date, end_date)
                print(f"  📊 Database returned: {len(db_data) if db_data else 'None'} days")
                if db_data is not None:
                    return {"data": db_data, "source": "database"}
            except Exception as db_err:
                print(f"⚠️ Database query failed, falling back to API: {db_err}")
                import traceback
                traceback.print_exc()

        # Fallback to API-based logic
        from report_logic import fetch_daily_reports
        data = fetch_daily_reports(start_date, end_date)

        return {"data": data, "source": "api"}

    except ImportError as e:
        # Log import error and return error response
        print(f"❌ Import error in daily_report: {e}")
        raise HTTPException(status_code=500, detail=f"Module import error: {e}")
    except Exception as e:
        print(f"❌ Error in daily_report: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "data": []}


# ==================== PRICING ENDPOINTS ====================

@app.get("/pricing/items")
async def get_items(market: str = None):
    """
    Get items list with optional market filter
    Tries database first, falls back to real-time API calls.
    Query param: ?market=US
    """
    try:
        # Try database first
        if DB_SERVICE_AVAILABLE and db_service.is_available():
            try:
                db_data = await db_service.get_items()
                if db_data is not None:
                    # Apply market filter if needed (stored data doesn't have market)
                    return {"data": db_data, "source": "database"}
            except Exception as db_err:
                print(f"⚠️ Database query failed, falling back to API: {db_err}")

        # Fallback to API-based logic
        from pricing_logic import fetch_items
        data = fetch_items(market_filter=market)
        return {"data": data, "source": "api"}
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
    For large batches (>5), runs in background with progress tracking
    """
    num_updates = len(req.updates)

    # For small batches, run synchronously
    if num_updates <= 5:
        try:
            from pricing_execution import execute_updates

            print(f"📝 Executing {num_updates} price updates...")
            result = execute_updates(req.updates)

            if result["updated_count"] > 0:
                from pricing_logic import invalidate_cache
                invalidate_cache()

            print(f"✅ Price updates complete: {result['updated_count']} updated, {result['failed_count']} failed")

            return {
                "success": True,
                "updated_count": result["updated_count"],
                "failed_count": result["failed_count"],
                "message": result["message"],
                "details": result.get("details", [])
            }
        except Exception as e:
            print(f"❌ Error in execute_price_updates: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to execute price updates: {str(e)}")

    # For larger batches, run in background
    task_id = str(uuid.uuid4())

    # Convert Pydantic models to dicts for background thread
    updates_data = [
        {
            "variant_id": u.variant_id,
            "new_price": u.new_price,
            "new_compare_at": u.new_compare_at,
            "compare_at_policy": u.compare_at_policy,
            "new_cogs": u.new_cogs,
            "notes": u.notes,
            "item": u.item,
            "current_price": u.current_price
        }
        for u in req.updates
    ]

    _BACKGROUND_TASKS[task_id] = {
        "task_id": task_id,
        "type": "price_update",
        "status": "pending",
        "total": num_updates,
        "progress": 0,
        "current_item": "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "updated_count": 0,
        "failed_count": 0,
        "message": ""
    }

    thread = threading.Thread(target=_run_price_update_background, args=(task_id, updates_data))
    thread.daemon = True
    thread.start()

    return {
        "success": True,
        "background": True,
        "task_id": task_id,
        "message": f"Started background update for {num_updates} variants. Poll /pricing/update-status/{task_id} for progress."
    }


@app.get("/pricing/update-status/{task_id}")
async def get_update_status(task_id: str):
    """
    Get status of a background price update
    """
    if task_id not in _BACKGROUND_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _BACKGROUND_TASKS[task_id]

    # Invalidate cache when completed
    if task["status"] == "completed" and task.get("updated_count", 0) > 0:
        try:
            from pricing_logic import invalidate_cache
            invalidate_cache()
        except:
            pass

    return {
        "task_id": task_id,
        "status": task["status"],
        "total": task["total"],
        "progress": task["progress"],
        "current_item": task.get("current_item", ""),
        "updated_count": task.get("updated_count", 0),
        "failed_count": task.get("failed_count", 0),
        "results": task.get("results", []) if task["status"] == "completed" else [],
        "message": task.get("message", ""),
        "error": task.get("error"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at")
    }


@app.post("/pricing/check-competitor-prices")
async def check_competitor_prices(req: CompetitorPriceCheckRequest):
    """
    Check competitor prices via SerpAPI (synchronous - for small batches only)
    For large batches, use /pricing/start-competitor-scan instead
    """
    # For small batches (<=5), run synchronously
    if len(req.variant_ids) <= 5:
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

    # For larger batches, redirect to background task
    task_id = str(uuid.uuid4())
    _BACKGROUND_TASKS[task_id] = {
        "task_id": task_id,
        "type": "competitor_scan",
        "status": "pending",
        "total": len(req.variant_ids),
        "progress": 0,
        "current_item": "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "message": ""
    }

    # Start background thread
    thread = threading.Thread(target=_run_competitor_scan_background, args=(task_id, req.variant_ids))
    thread.daemon = True
    thread.start()

    return {
        "success": True,
        "background": True,
        "task_id": task_id,
        "message": f"Started background scan for {len(req.variant_ids)} variants. Poll /pricing/scan-status/{task_id} for progress."
    }


@app.post("/pricing/start-competitor-scan")
async def start_competitor_scan(req: CompetitorPriceCheckRequest):
    """
    Start a background competitor price scan (non-blocking)
    Returns task_id to poll for progress
    """
    if not req.variant_ids:
        raise HTTPException(status_code=400, detail="No variant IDs provided")

    task_id = str(uuid.uuid4())
    _BACKGROUND_TASKS[task_id] = {
        "task_id": task_id,
        "type": "competitor_scan",
        "status": "pending",
        "total": len(req.variant_ids),
        "progress": 0,
        "current_item": "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "message": ""
    }

    # Start background thread
    thread = threading.Thread(target=_run_competitor_scan_background, args=(task_id, req.variant_ids))
    thread.daemon = True
    thread.start()

    return {
        "success": True,
        "task_id": task_id,
        "total": len(req.variant_ids),
        "message": f"Started background scan for {len(req.variant_ids)} variants"
    }


@app.get("/pricing/scan-status/{task_id}")
async def get_scan_status(task_id: str):
    """
    Get status of a background competitor scan
    """
    if task_id not in _BACKGROUND_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _BACKGROUND_TASKS[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "total": task["total"],
        "progress": task["progress"],
        "current_item": task.get("current_item", ""),
        "results": task.get("results", []) if task["status"] == "completed" else [],
        "message": task.get("message", ""),
        "error": task.get("error"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at")
    }


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


@app.get("/pricing/scan-history")
async def get_scan_history(limit: int = 100):
    """
    Get competitor scan history
    Query param: ?limit=100
    """
    try:
        from pricing_logic import get_scan_history as fetch_history
        data = fetch_history(limit=limit)
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@app.post("/pricing/refresh-cache")
async def refresh_cache():
    """
    Invalidate all caches to force fresh data fetch
    Call this after price updates, competitor scans, etc.
    """
    try:
        from pricing_logic import invalidate_cache
        result = invalidate_cache()
        return {
            "success": True,
            "message": f"Cleared {result['cleared']} cache entries",
            "cleared": result["cleared"]
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/pricing/korealy-sync")
async def sync_korealy_to_shopify_endpoint(req: KorealySyncRequest):
    """
    Sync selected Korealy COGS to Shopify
    For batches > 3, runs in background with progress tracking
    """
    try:
        print(f"🔄 Korealy sync request received with {len(req.updates)} updates")
        print(f"📋 Raw updates: {req.updates[:3]}...")  # Show first 3 for debugging

        # Build variant_ids list and cogs_map from updates
        variant_ids = []
        korealy_cogs_map = {}
        skipped = []

        for update in req.updates:
            variant_id = update.get("variant_id")
            new_cogs = update.get("new_cogs") or update.get("korealy_cogs")  # Try both field names

            print(f"  Processing: variant_id={variant_id}, new_cogs={new_cogs}, keys={list(update.keys())}")

            # Skip records without valid variant_id or cogs
            if not variant_id or variant_id == "null" or variant_id == "None" or str(variant_id) == "None":
                skipped.append({
                    "reason": "No Shopify mapping",
                    "korealy_title": update.get("korealy_title", "Unknown"),
                    "raw_variant_id": variant_id
                })
                continue

            if new_cogs is None:
                skipped.append({
                    "reason": "No Korealy COGS value",
                    "variant_id": variant_id,
                    "update_keys": list(update.keys())
                })
                continue

            variant_ids.append(str(variant_id))
            korealy_cogs_map[str(variant_id)] = float(new_cogs)

        print(f"✅ Valid updates: {len(variant_ids)}, Skipped: {len(skipped)}")

        if not variant_ids:
            print(f"⚠️ No valid items to sync!")
            print(f"📋 Skipped items: {skipped[:5]}...")  # Show first 5 skipped
            return {
                "success": False,
                "updated_count": 0,
                "failed_count": 0,
                "skipped_count": len(skipped),
                "message": f"No valid items to sync. {len(skipped)} items skipped (no Shopify mapping or missing COGS).",
                "details": skipped[:20],  # Return first 20 skipped for debugging
                "debug": {
                    "total_received": len(req.updates),
                    "sample_update": req.updates[0] if req.updates else None
                }
            }

        num_updates = len(variant_ids)

        # For small batches (<=3), run synchronously
        if num_updates <= 3:
            from korealy_reconciliation import sync_korealy_to_shopify as sync_cogs
            result = sync_cogs(variant_ids, korealy_cogs_map)

            return {
                "success": True,
                "updated_count": result["updated_count"],
                "failed_count": result["failed_count"],
                "skipped_count": len(skipped),
                "message": result["message"] + (f" ({len(skipped)} pre-skipped)" if skipped else ""),
                "details": result.get("details", [])
            }

        # For larger batches, run in background
        task_id = str(uuid.uuid4())
        _BACKGROUND_TASKS[task_id] = {
            "task_id": task_id,
            "type": "korealy_sync",
            "status": "pending",
            "total": num_updates,
            "progress": 0,
            "current_item": "",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "results": [],
            "updated_count": 0,
            "failed_count": 0,
            "skipped_count": len(skipped),
            "message": ""
        }

        thread = threading.Thread(target=_run_korealy_sync_background, args=(task_id, variant_ids, korealy_cogs_map))
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "background": True,
            "task_id": task_id,
            "message": f"Started background sync for {num_updates} variants. Poll /pricing/korealy-sync-status/{task_id} for progress."
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import korealy_reconciliation module: {e}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to sync Korealy COGS: {str(e)}")


@app.get("/pricing/korealy-sync-status/{task_id}")
async def get_korealy_sync_status(task_id: str):
    """
    Get status of a background Korealy sync
    """
    if task_id not in _BACKGROUND_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _BACKGROUND_TASKS[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "total": task["total"],
        "progress": task["progress"],
        "current_item": task.get("current_item", ""),
        "updated_count": task.get("updated_count", 0),
        "failed_count": task.get("failed_count", 0),
        "skipped_count": task.get("skipped_count", 0),
        "results": task.get("results", []) if task["status"] == "completed" else [],
        "message": task.get("message", ""),
        "error": task.get("error"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at")
    }


# ==================== ORDER REPORT ENDPOINT ====================

class OrderReportRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@app.post("/order-report")
async def order_report(req: OrderReportRequest):
    """
    Return order-level breakdown with analytics for the date range.
    Tries database first, falls back to real-time API calls.
    """
    try:
        start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()

        print(f"📋 Order report request: {start_date} to {end_date}")

        if start_date > end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        # Try database first
        if DB_SERVICE_AVAILABLE and db_service.is_available():
            print(f"  📊 Trying database query...")
            try:
                db_data = await db_service.get_orders(start_date, end_date)
                print(f"  📊 Database returned: {len(db_data) if db_data else 'None'} orders")
                if db_data is not None:
                    return {"data": db_data, "source": "database"}
            except Exception as db_err:
                print(f"⚠️ Database query failed, falling back to API: {db_err}")
                import traceback
                traceback.print_exc()

        # Fallback to API-based logic
        from order_report_logic import fetch_order_report
        data = fetch_order_report(start_date, end_date)

        return {"data": data, "source": "api"}

    except ImportError as e:
        print(f"❌ Import error in order_report: {e}")
        raise HTTPException(status_code=500, detail=f"Module import error: {e}")
    except Exception as e:
        print(f"❌ Error in order_report: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "data": []}


# ==================== BESTSELLERS ENDPOINTS ====================

@app.get("/bestsellers/{days}")
async def get_bestsellers(days: int = 30):
    """
    Get best selling products for the specified number of days.
    Tries database first, falls back to real-time API calls.
    Supported values: 7, 30, 60
    """
    if days not in [7, 30, 60]:
        raise HTTPException(status_code=400, detail="Days must be 7, 30, or 60")

    try:
        # Try database first
        if DB_SERVICE_AVAILABLE and db_service.is_available():
            try:
                db_data = await db_service.get_bestsellers(days=days)
                if db_data is not None:
                    return {"success": True, "data": db_data, "source": "database"}
            except Exception as db_err:
                print(f"⚠️ Database query failed, falling back to API: {db_err}")

        # Fallback to API-based logic
        from bestsellers_logic import fetch_bestsellers
        data = fetch_bestsellers(days)
        return {"success": True, "data": data, "source": "api"}
    except ImportError as e:
        print(f"❌ Import error in get_bestsellers: {e}")
        raise HTTPException(status_code=500, detail=f"Module import error: {e}")
    except Exception as e:
        print(f"❌ Error in get_bestsellers: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class VariantOrderCountRequest(BaseModel):
    variant_ids: List[str]
    days: int = 30


@app.post("/variant-order-counts")
async def get_variant_order_counts(req: VariantOrderCountRequest):
    """
    Get order count for specific variant IDs in the last N days.
    Used to add order count to target prices.
    """
    try:
        from bestsellers_logic import get_variant_order_count
        counts = get_variant_order_count(req.variant_ids, req.days)
        return {"success": True, "counts": counts}
    except ImportError as e:
        print(f"❌ Import error in get_variant_order_counts: {e}")
        raise HTTPException(status_code=500, detail=f"Module import error: {e}")
    except Exception as e:
        print(f"❌ Error in get_variant_order_counts: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("simple_server:app", host="0.0.0.0", port=port, reload=False)
