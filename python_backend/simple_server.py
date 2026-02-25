"""
Simple FastAPI server for dashboard reports - NO automation, NO Telegram, NO complexity
Just: fetch data from APIs → calculate metrics → return JSON

Supports PostgreSQL database with fallback to real-time API calls
"""
import os
import uuid
import asyncio
import threading
import jwt
import httpx
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import pytz

# JWT Settings
JWT_SECRET = os.getenv("JWT_SECRET", "mirai-dashboard-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 1 week

# Google OAuth Settings
GOOGLE_CLIENT_ID = os.getenv("VITE_GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
# First admin email - this user will be created as admin on first login
FIRST_ADMIN_EMAIL = os.getenv("FIRST_ADMIN_EMAIL", "kapoosha@gmail.com")
ALLOWED_EMAILS = [e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()]
# Always allow first admin email
if FIRST_ADMIN_EMAIL and FIRST_ADMIN_EMAIL not in ALLOWED_EMAILS:
    ALLOWED_EMAILS.append(FIRST_ADMIN_EMAIL)

security = HTTPBearer(auto_error=False)

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
    """Initialize database and log configuration on startup"""
    print("=" * 60)
    print("🚀 Mirai Reports API Starting Up")
    print("=" * 60)

    # Initialize database tables (creates new tables if they don't exist)
    try:
        from database.connection import init_db
        await init_db()
        print("✅ Database tables initialized")
    except Exception as e:
        print(f"⚠️ Database init: {e}")

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
    Get competitor scan history - tries database first, falls back to JSON file
    Query param: ?limit=100
    """
    try:
        # Try database first for faster loading
        if DB_SERVICE_AVAILABLE:
            from database.service import db_service
            db_data = await db_service.get_scan_history(limit=limit)
            if db_data is not None and len(db_data) > 0:
                print(f"  📊 Scan history from database: {len(db_data)} records")
                return {"data": db_data, "source": "database"}

        # Fallback to JSON file
        from pricing_logic import get_scan_history as fetch_history
        data = fetch_history(limit=limit)
        return {"data": data, "source": "json"}
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


# ==================== AUTHENTICATION ====================

class GoogleAuthRequest(BaseModel):
    token: str  # Google ID token from frontend


class AddUserRequest(BaseModel):
    email: str
    is_admin: bool = False


async def verify_google_token(token: str) -> dict:
    """Verify Google ID token and return user info"""
    try:
        # Verify with Google
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")

            data = response.json()

            # Verify audience (client ID)
            if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail="Token not for this application")

            return {
                "email": data.get("email"),
                "name": data.get("name"),
                "picture": data.get("picture"),
                "google_id": data.get("sub")
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify token: {e}")


def create_jwt_token(user_data: dict) -> str:
    """Create JWT token for authenticated user"""
    payload = {
        "sub": user_data["email"],
        "name": user_data.get("name", ""),
        "picture": user_data.get("picture", ""),
        "is_admin": user_data.get("is_admin", False),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    """Get current user from JWT token"""
    if not credentials:
        return None

    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "email": payload.get("sub"),
            "name": payload.get("name"),
            "picture": payload.get("picture"),
            "is_admin": payload.get("is_admin", False)
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """Require authentication"""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Require admin role"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.post("/auth/google")
async def google_login(req: GoogleAuthRequest):
    """
    Login with Google ID token.
    Returns JWT token if user is allowed.
    """
    try:
        # Verify Google token
        google_user = await verify_google_token(req.token)
        email = google_user["email"]

        print(f"🔐 Login attempt: {email}")

        # Check if user exists in database
        if DB_SERVICE_AVAILABLE:
            from database.connection import get_db, is_db_configured
            from database.models import User
            from sqlalchemy import select, func

            async with get_db() as db:
                # Case-insensitive email lookup
                result = await db.execute(select(User).where(func.lower(User.email) == email.lower().strip()))
                user = result.scalar_one_or_none()

                if not user:
                    # Check if email is in allowed list
                    is_first_user = False
                    user_count = await db.execute(select(User))
                    if not user_count.scalars().all():
                        is_first_user = True

                    # Check if user is allowed (first user or in allowed list or is first admin email)
                    is_first_admin = email.strip().lower() == FIRST_ADMIN_EMAIL.strip().lower()
                    is_allowed = email.strip() in ALLOWED_EMAILS or is_first_user or is_first_admin

                    if not is_allowed:
                        print(f"❌ Email not allowed: {email}")
                        raise HTTPException(status_code=403, detail="Email not authorized. Contact admin to be added.")

                    # Create new user - first user or first admin email becomes admin
                    make_admin = is_first_user or is_first_admin
                    user = User(
                        email=email,
                        name=google_user.get("name"),
                        picture=google_user.get("picture"),
                        google_id=google_user.get("google_id"),
                        is_admin=make_admin,
                        is_active=True
                    )
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                    print(f"✅ Created new user: {email} (admin={make_admin})")
                else:
                    if not user.is_active:
                        raise HTTPException(status_code=403, detail="Account is disabled")

                    # Update last login
                    user.last_login = datetime.utcnow()
                    user.name = google_user.get("name") or user.name
                    user.picture = google_user.get("picture") or user.picture
                    await db.commit()
                    print(f"✅ User logged in: {email}")

                # Create JWT token
                token = create_jwt_token({
                    "email": user.email,
                    "name": user.name,
                    "picture": user.picture,
                    "is_admin": user.is_admin
                })

                return {
                    "success": True,
                    "token": token,
                    "user": {
                        "email": user.email,
                        "name": user.name,
                        "picture": user.picture,
                        "is_admin": user.is_admin
                    }
                }
        else:
            # No database - check allowed emails only
            if email.strip() not in [e.strip() for e in ALLOWED_EMAILS if e.strip()]:
                raise HTTPException(status_code=403, detail="Email not authorized")

            token = create_jwt_token({
                "email": email,
                "name": google_user.get("name"),
                "picture": google_user.get("picture"),
                "is_admin": True  # Without DB, all allowed users are admin
            })

            return {
                "success": True,
                "token": token,
                "user": {
                    "email": email,
                    "name": google_user.get("name"),
                    "picture": google_user.get("picture"),
                    "is_admin": True
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Auth error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/auth/me")
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info"""
    return {"user": user}


@app.get("/auth/users")
async def list_users(user: dict = Depends(require_admin)):
    """List all users (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        return {"users": [], "message": "Database not available"}

    from database.connection import get_db, is_db_configured
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

        return {
            "users": [
                {
                    "id": u.id,
                    "email": u.email,
                    "name": u.name,
                    "picture": u.picture,
                    "is_active": u.is_active,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login": u.last_login.isoformat() if u.last_login else None
                }
                for u in users
            ]
        }


@app.post("/auth/users")
async def add_user(req: AddUserRequest, user: dict = Depends(require_admin)):
    """Add a new allowed user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import User
    from sqlalchemy import select, func

    email_clean = req.email.strip().lower()

    async with get_db() as db:
        # Check if user already exists (case-insensitive)
        result = await db.execute(select(User).where(func.lower(User.email) == email_clean))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        # Create user (they'll complete profile on first login)
        # Store email in lowercase for consistent lookup
        new_user = User(
            email=email_clean,
            is_admin=req.is_admin,
            is_active=True
        )
        db.add(new_user)
        await db.commit()

        print(f"✅ Added new user: {email_clean} (admin={req.is_admin})")

        return {"success": True, "message": f"User {email_clean} added successfully"}


@app.delete("/auth/users/{user_id}")
async def delete_user(user_id: int, user: dict = Depends(require_admin)):
    """Delete a user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        target_user = result.scalar_one_or_none()

        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Can't delete yourself
        if target_user.email == user["email"]:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")

        await db.delete(target_user)
        await db.commit()

        return {"success": True, "message": f"User {target_user.email} deleted"}


@app.put("/auth/users/{user_id}/toggle-admin")
async def toggle_admin(user_id: int, user: dict = Depends(require_admin)):
    """Toggle admin status for a user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        target_user = result.scalar_one_or_none()

        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Can't remove your own admin
        if target_user.email == user["email"]:
            raise HTTPException(status_code=400, detail="Cannot modify your own admin status")

        target_user.is_admin = not target_user.is_admin
        await db.commit()

        return {"success": True, "is_admin": target_user.is_admin}


# ==================== SUPPORT ENDPOINTS ====================

class SupportEmailCreate(BaseModel):
    thread_id: str
    message_id: Optional[str] = None
    customer_email: str
    customer_name: Optional[str] = None
    subject: str
    content: str
    content_html: Optional[str] = None
    inbox_type: Optional[str] = "support"  # 'emma' (sales) or 'support'
    sender_type: Optional[str] = None  # 'customer', 'supplier', 'automated', 'internal'


class SupportEmailUpdate(BaseModel):
    status: Optional[str] = None
    classification: Optional[str] = None
    intent: Optional[str] = None
    priority: Optional[str] = None
    sender_type: Optional[str] = None  # 'customer', 'supplier', 'automated', 'internal'
    ai_draft: Optional[str] = None
    draft_error: Optional[str] = None  # Error message if draft generation failed
    final_content: Optional[str] = None


@app.get("/support/emails")
async def list_support_emails(
    status: Optional[str] = None,
    classification: Optional[str] = None,
    inbox_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user)
):
    """List support emails with optional filters"""
    print(f"📧 [support/emails] DB_SERVICE_AVAILABLE={DB_SERVICE_AVAILABLE}, status={status}, inbox_type={inbox_type}")

    if not DB_SERVICE_AVAILABLE:
        print("📧 [support/emails] Database service not available")
        return {"emails": [], "total": 0, "message": "Database not available"}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select, func, desc
    from sqlalchemy.orm import selectinload

    try:
        async with get_db() as db:
            # Build query
            query = select(SupportEmail).options(
                selectinload(SupportEmail.messages)
            ).order_by(desc(SupportEmail.received_at))

            # Apply filters
            if status:
                query = query.where(SupportEmail.status == status)
            if classification:
                query = query.where(SupportEmail.classification == classification)
            if inbox_type:
                query = query.where(SupportEmail.inbox_type == inbox_type)

            # Get total count
            count_query = select(func.count(SupportEmail.id))
            if status:
                count_query = count_query.where(SupportEmail.status == status)
            if classification:
                count_query = count_query.where(SupportEmail.classification == classification)
            if inbox_type:
                count_query = count_query.where(SupportEmail.inbox_type == inbox_type)
            total_result = await db.execute(count_query)
            total = total_result.scalar() or 0

            # Apply pagination
            query = query.offset(offset).limit(limit)

            result = await db.execute(query)
            emails = result.scalars().all()

            print(f"📧 [support/emails] Found {len(emails)} emails, total={total}")

            return {
                "emails": [
                    {
                        "id": e.id,
                        "thread_id": e.thread_id,
                        "customer_email": e.customer_email,
                        "customer_name": e.customer_name,
                        "subject": e.subject,
                        "status": e.status,
                        "classification": e.classification,
                        "intent": e.intent,
                        "priority": e.priority,
                        "sales_opportunity": e.sales_opportunity,
                        "inbox_type": e.inbox_type,
                        "sender_type": getattr(e, 'sender_type', 'customer'),
                        "ai_confidence": float(e.ai_confidence) if e.ai_confidence else None,
                        "received_at": e.received_at.isoformat() if e.received_at else None,
                        "messages_count": len(e.messages),
                        "latest_message": e.messages[-1].content[:200] if e.messages else None,
                        "ai_draft": e.messages[-1].ai_draft if e.messages and e.messages[-1].ai_draft else None
                    }
                    for e in emails
                ],
                "total": total
            }
    except Exception as e:
        print(f"❌ [support/emails] Database error: {e}")
        import traceback
        traceback.print_exc()
        return {"emails": [], "total": 0, "error": str(e)}


@app.get("/support/emails/{email_id}")
async def get_support_email(email_id: int, user: dict = Depends(get_current_user)):
    """Get a single support email with all messages"""
    print(f"📧 [support/emails/{email_id}] DB_SERVICE_AVAILABLE={DB_SERVICE_AVAILABLE}")

    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    try:
        async with get_db() as db:
            result = await db.execute(
                select(SupportEmail)
                .options(selectinload(SupportEmail.messages))
                .where(SupportEmail.id == email_id)
            )
            email = result.scalar_one_or_none()

            print(f"📧 [support/emails/{email_id}] Found email: {email is not None}")

            if not email:
                raise HTTPException(status_code=404, detail="Email not found")

            return {
                "id": email.id,
                "thread_id": email.thread_id,
                "customer_email": email.customer_email,
                "customer_name": email.customer_name,
                "subject": email.subject,
                "status": email.status,
                "classification": email.classification,
                "intent": email.intent,
                "priority": email.priority,
                "sales_opportunity": email.sales_opportunity,
                "ai_confidence": float(email.ai_confidence) if email.ai_confidence else None,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "created_at": email.created_at.isoformat() if email.created_at else None,
                "messages": [
                    {
                        "id": m.id,
                        "direction": m.direction,
                        "sender_email": m.sender_email,
                        "sender_name": m.sender_name,
                        "content": m.content,
                        "ai_draft": m.ai_draft,
                        "ai_reasoning": m.ai_reasoning,
                        "final_content": m.final_content,
                        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                        "created_at": m.created_at.isoformat() if m.created_at else None
                    }
                    for m in email.messages
                ]
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [support/emails/{email_id}] Database error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/support-email")
async def webhook_support_email(req: SupportEmailCreate):
    """Webhook for internal services (Emma poller) - no auth required for internal use"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select

    async with get_db() as db:
        # Check if thread already exists
        result = await db.execute(
            select(SupportEmail).where(SupportEmail.thread_id == req.thread_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Add message to existing thread
            message = SupportMessage(
                email_id=existing.id,
                direction="inbound",
                sender_email=req.customer_email,
                sender_name=req.customer_name,
                content=req.content,
                content_html=req.content_html
            )
            db.add(message)
            existing.status = "pending"
            await db.commit()
            return {"id": existing.id, "message": "Message added to existing thread"}

        # Create new email thread
        email = SupportEmail(
            thread_id=req.thread_id,
            message_id=req.message_id,
            customer_email=req.customer_email,
            customer_name=req.customer_name,
            subject=req.subject,
            status="pending",
            inbox_type=req.inbox_type or "support",
            sender_type=req.sender_type or "customer",  # Set sender_type on creation
            received_at=datetime.utcnow()
        )
        db.add(email)
        await db.flush()

        # Create first message
        message = SupportMessage(
            email_id=email.id,
            direction="inbound",
            sender_email=req.customer_email,
            sender_name=req.customer_name,
            content=req.content,
            content_html=req.content_html
        )
        db.add(message)
        await db.commit()

        return {"id": email.id, "message": "Email created successfully"}


@app.patch("/webhook/support-email/{email_id}")
async def webhook_update_support_email(email_id: int, req: SupportEmailUpdate):
    """Webhook for internal services (Emma) to update email drafts - no auth required"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail)
            .options(selectinload(SupportEmail.messages))
            .where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        # Update classification fields
        if req.classification:
            email.classification = req.classification
        if req.intent:
            email.intent = req.intent
        if req.priority:
            email.priority = req.priority
        if req.sender_type:
            email.sender_type = req.sender_type

        # Update AI draft on latest message
        inbound_msgs = [m for m in email.messages if m.direction == "inbound"]
        if inbound_msgs:
            latest_msg = inbound_msgs[-1]
            # Set AI draft if provided (even empty string to clear it)
            if req.ai_draft is not None:
                latest_msg.ai_draft = req.ai_draft if req.ai_draft else None
            # Store draft error in ai_reasoning field if provided
            if req.draft_error:
                latest_msg.ai_reasoning = f"[ERROR] {req.draft_error}"

        # Set status - use explicit status if provided, otherwise infer from ai_draft
        if req.status:
            email.status = req.status
        elif req.ai_draft:  # Only auto-set draft_ready if there's actual content
            email.status = "draft_ready"

        await db.commit()
        return {"success": True, "status": email.status}


@app.post("/support/emails")
async def create_support_email(req: SupportEmailCreate, user: dict = Depends(get_current_user)):
    """Create a new support email (authenticated endpoint for frontend)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select

    async with get_db() as db:
        # Check if thread already exists
        result = await db.execute(
            select(SupportEmail).where(SupportEmail.thread_id == req.thread_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Add message to existing thread
            message = SupportMessage(
                email_id=existing.id,
                direction="inbound",
                sender_email=req.customer_email,
                sender_name=req.customer_name,
                content=req.content,
                content_html=req.content_html
            )
            db.add(message)
            existing.status = "pending"  # Reset to pending for new message
            await db.commit()
            return {"id": existing.id, "message": "Message added to existing thread"}

        # Create new email thread
        email = SupportEmail(
            thread_id=req.thread_id,
            message_id=req.message_id,
            customer_email=req.customer_email,
            customer_name=req.customer_name,
            subject=req.subject,
            status="pending",
            inbox_type=req.inbox_type or "support",
            sender_type=req.sender_type or "customer",  # Set sender_type on creation
            received_at=datetime.utcnow()
        )
        db.add(email)
        await db.flush()

        # Create first message
        message = SupportMessage(
            email_id=email.id,
            direction="inbound",
            sender_email=req.customer_email,
            sender_name=req.customer_name,
            content=req.content,
            content_html=req.content_html
        )
        db.add(message)
        await db.commit()

        return {"id": email.id, "message": "Email created successfully"}


@app.patch("/support/emails/{email_id}")
async def update_support_email(
    email_id: int,
    req: SupportEmailUpdate,
    user: dict = Depends(get_current_user)
):
    """Update support email status, classification, or AI draft"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail)
            .options(selectinload(SupportEmail.messages))
            .where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        # Update fields
        if req.status:
            email.status = req.status
        if req.classification:
            email.classification = req.classification
        if req.intent:
            email.intent = req.intent
        if req.priority:
            email.priority = req.priority

        # Update AI draft on latest message or create outbound message
        if req.ai_draft:
            # Find latest inbound message and add draft
            inbound_msgs = [m for m in email.messages if m.direction == "inbound"]
            if inbound_msgs:
                inbound_msgs[-1].ai_draft = req.ai_draft
            email.status = "draft_ready"

        # Update final content
        if req.final_content:
            # Create outbound message with final content
            outbound = SupportMessage(
                email_id=email.id,
                direction="outbound",
                sender_email="support@miraiskin.com",
                sender_name="Mirai Support",
                content=req.final_content,
                final_content=req.final_content,
                approved_by=user.get("user_id"),
                approved_at=datetime.utcnow()
            )
            db.add(outbound)
            email.status = "approved"

        await db.commit()
        return {"success": True, "status": email.status}


@app.post("/support/emails/{email_id}/approve")
async def approve_support_email(email_id: int, user: dict = Depends(get_current_user)):
    """Approve AI draft and mark for sending"""
    print(f"📧 [APPROVE] Starting approval for email_id={email_id}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [APPROVE] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail)
            .options(selectinload(SupportEmail.messages))
            .where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            print(f"❌ [APPROVE] Email {email_id} not found")
            raise HTTPException(status_code=404, detail="Email not found")

        print(f"📧 [APPROVE] Found email from {email.customer_email}, subject: {email.subject[:50] if email.subject else 'N/A'}")

        # Get latest AI draft
        ai_draft = None
        for msg in reversed(email.messages):
            if msg.ai_draft:
                ai_draft = msg.ai_draft
                break

        if not ai_draft:
            print(f"❌ [APPROVE] No AI draft found for email {email_id}")
            raise HTTPException(status_code=400, detail="No AI draft to approve")

        print(f"📧 [APPROVE] Found AI draft ({len(ai_draft)} chars), creating outbound message")

        # Create approved outbound message
        outbound = SupportMessage(
            email_id=email.id,
            direction="outbound",
            sender_email="support@miraiskin.com",
            sender_name="Mirai Support",
            content=ai_draft,
            final_content=ai_draft,
            approved_by=user.get("user_id"),
            approved_at=datetime.utcnow(),
            sent_at=datetime.utcnow()  # Mark as sent for Activity Center tracking
        )
        db.add(outbound)
        email.status = "approved"
        await db.commit()

        print(f"✅ [APPROVE] Email {email_id} approved successfully by user {user.get('user_id')}")
        return {"success": True, "message": "Email approved for sending"}


@app.post("/support/migrate-sent-at")
async def migrate_sent_at(user: dict = Depends(get_current_user)):
    """
    One-time migration: Set sent_at = approved_at for messages that were approved but don't have sent_at.
    This backfills Activity Center tracking for existing approved emails.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import SupportMessage
    from sqlalchemy import select, update, and_

    async with get_db() as db:
        # Find messages with approved_at but no sent_at
        result = await db.execute(
            update(SupportMessage)
            .where(and_(
                SupportMessage.approved_at.isnot(None),
                SupportMessage.sent_at.is_(None)
            ))
            .values(sent_at=SupportMessage.approved_at)
        )

        updated_count = result.rowcount
        await db.commit()

        return {
            "success": True,
            "message": f"Migrated {updated_count} messages: set sent_at = approved_at",
            "updated_count": updated_count
        }


@app.post("/admin/backfill-shipping-costs")
async def backfill_shipping_costs(user: dict = Depends(get_current_user)):
    """
    Backfill shipping_cost for all orders using the shipping matrix.
    This recalculates shipping costs based on weight and country.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import Order
    from sqlalchemy import select
    from master_report_mirai import _lookup_matrix_shipping_usd, _canonical_geo

    updated_count = 0
    errors = []

    async with get_db() as db:
        # Get all orders
        result = await db.execute(select(Order))
        orders = result.scalars().all()

        for order in orders:
            try:
                weight_kg = (order.total_weight_g or 0) / 1000.0
                country_code = order.country_code or ""
                country_name = order.country or ""
                geo = _canonical_geo(country_name, country_code)
                shipping_cost = _lookup_matrix_shipping_usd(geo, weight_kg)

                if shipping_cost != (float(order.shipping_cost) if order.shipping_cost else 0):
                    order.shipping_cost = round(shipping_cost, 2)
                    updated_count += 1
            except Exception as e:
                errors.append(f"Order {order.order_name}: {str(e)}")

        await db.commit()

    return {
        "success": True,
        "message": f"Updated shipping costs for {updated_count} orders",
        "updated_count": updated_count,
        "errors": errors[:10] if errors else []
    }


@app.post("/support/emails/{email_id}/reject")
async def reject_support_email(email_id: int, user: dict = Depends(get_current_user)):
    """Reject/archive email"""
    print(f"📧 [REJECT] Starting rejection for email_id={email_id}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [REJECT] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail).where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            print(f"❌ [REJECT] Email {email_id} not found")
            raise HTTPException(status_code=404, detail="Email not found")

        print(f"📧 [REJECT] Rejecting email from {email.customer_email}")
        email.status = "rejected"
        await db.commit()

        print(f"✅ [REJECT] Email {email_id} rejected successfully")
        return {"success": True, "message": "Email rejected"}


class ResolveRequest(BaseModel):
    resolution: str  # resolved, refunded, replaced, waiting_customer, escalated, no_action_needed
    resolution_notes: Optional[str] = None


@app.post("/support/emails/{email_id}/resolve")
async def resolve_support_email(email_id: int, req: ResolveRequest, user: dict = Depends(get_current_user)):
    """
    Mark a support ticket as resolved with a resolution type.
    """
    print(f"📧 [RESOLVE] Starting resolution for email_id={email_id}, resolution={req.resolution}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [RESOLVE] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail).where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            print(f"❌ [RESOLVE] Email {email_id} not found")
            raise HTTPException(status_code=404, detail="Email not found")

        print(f"📧 [RESOLVE] Resolving email from {email.customer_email}, resolution: {req.resolution}")

        # Calculate resolution time
        resolution_time = None
        if email.received_at:
            from datetime import datetime
            resolution_time = int((datetime.utcnow() - email.received_at).total_seconds() / 60)
            print(f"📧 [RESOLVE] Resolution time: {resolution_time} minutes")

        # Update ticket
        email.status = "resolved"
        email.resolution = req.resolution
        email.resolution_notes = req.resolution_notes
        email.resolved_by = user.get("user_id")
        email.resolved_at = datetime.utcnow()
        email.resolution_time_minutes = resolution_time

        await db.commit()

        print(f"✅ [RESOLVE] Email {email_id} resolved as '{req.resolution}' by user {user.get('user_id')}")
        return {
            "success": True,
            "message": f"Ticket resolved as: {req.resolution}",
            "resolution_time_minutes": resolution_time
        }


class RegenerateRequest(BaseModel):
    user_hints: Optional[str] = None  # Manager guidance for Emma


@app.post("/support/emails/{email_id}/regenerate")
async def regenerate_ai_response(
    email_id: int,
    req: Optional[RegenerateRequest] = None,
    user: dict = Depends(get_current_user)
):
    """
    Regenerate AI draft for an email by calling Emma service.

    Optional request body:
        user_hints: Manager guidance on how Emma should respond (e.g., "Offer a 10% discount", "Be more apologetic")
    """
    print(f"📧 [REGENERATE] Starting AI regeneration for email_id={email_id}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [REGENERATE] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    import httpx
    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail)
            .options(selectinload(SupportEmail.messages))
            .where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            print(f"❌ [REGENERATE] Email {email_id} not found")
            raise HTTPException(status_code=404, detail="Email not found")

        print(f"📧 [REGENERATE] Found email from {email.customer_email}")

        # Get the latest inbound message
        inbound_msgs = [m for m in email.messages if m.direction == "inbound"]
        if not inbound_msgs:
            print(f"❌ [REGENERATE] No inbound message found for email {email_id}")
            raise HTTPException(status_code=400, detail="No inbound message to respond to")

        latest_msg = inbound_msgs[-1]

        # Set status to pending while generating
        email.status = "pending"
        await db.commit()
        print(f"📧 [REGENERATE] Status set to pending, calling Emma service")

    # Call Emma service to regenerate the AI response
    emma_url = os.getenv("EMMA_SERVICE_URL", "https://emma-service.onrender.com")
    print(f"📧 [REGENERATE] Emma URL: {emma_url}")

    # Extract user hints if provided
    user_hints = req.user_hints if req else None
    if user_hints:
        print(f"📧 [REGENERATE] Manager hints provided: {user_hints[:100]}...")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = {
                "email_id": email_id,
                "customer_email": email.customer_email,
                "customer_name": email.customer_name,
                "subject": email.subject,
                "content": latest_msg.content
            }
            # Add user hints if provided
            if user_hints:
                payload["user_hints"] = user_hints

            print(f"📧 [REGENERATE] Sending request to Emma: {payload.get('customer_email')}")
            response = await client.post(
                f"{emma_url}/generate-email-draft",
                json=payload
            )

            if response.status_code == 200:
                print(f"✅ [REGENERATE] Emma responded successfully for email {email_id}")
                return {"success": True, "message": "AI response generation started"}
            else:
                print(f"❌ [REGENERATE] Emma error: status {response.status_code}, body: {response.text[:200]}")
                # Update status to failed
                async with get_db() as db:
                    result = await db.execute(
                        select(SupportEmail).where(SupportEmail.id == email_id)
                    )
                    email = result.scalar_one_or_none()
                    if email:
                        email.status = "draft_failed"
                        await db.commit()

                return {"success": False, "error": f"Emma service error: {response.status_code}"}

    except Exception as e:
        print(f"❌ [REGENERATE] Exception calling Emma: {str(e)}")
        # Update status to failed
        async with get_db() as db:
            result = await db.execute(
                select(SupportEmail).where(SupportEmail.id == email_id)
            )
            email = result.scalar_one_or_none()
            if email:
                email.status = "draft_failed"
                await db.commit()

        return {"success": False, "error": str(e)}


@app.post("/support/emails/{email_id}/mark-seen")
async def mark_email_seen(email_id: int, user: dict = Depends(get_current_user)):
    """
    Mark an email as 'seen' when the user opens the ticket detail.
    Only updates if the current status is 'new'.
    """
    print(f"👁️ [MARK-SEEN] Marking email_id={email_id} as seen, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        return {"success": False, "error": "Database not available"}

    from database.connection import get_db
    from database.models import SupportEmail
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(SupportEmail).where(SupportEmail.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        # Only change from 'new' to 'seen'
        if email.status == "new":
            email.status = "seen"
            await db.commit()
            print(f"✅ [MARK-SEEN] Email {email_id} marked as seen")
            return {"success": True, "status": "seen", "changed": True}
        else:
            print(f"ℹ️ [MARK-SEEN] Email {email_id} already has status: {email.status}")
            return {"success": True, "status": email.status, "changed": False}


@app.post("/support/reset-to-new")
async def reset_all_to_new(user: dict = Depends(get_current_user)):
    """
    [TEST ENDPOINT] Reset all non-resolved tickets to 'new' status.
    Used for testing the new/seen functionality.
    """
    print(f"🔄 [RESET-TO-NEW] Resetting all tickets to 'new', user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        return {"success": False, "error": "Database not available"}

    from database.connection import get_db
    from database.models import SupportEmail
    from sqlalchemy import select, update

    async with get_db() as db:
        # Reset non-resolved tickets to 'new'
        result = await db.execute(
            update(SupportEmail)
            .where(SupportEmail.status.notin_(['resolved', 'sent']))
            .values(status='new')
        )
        count = result.rowcount
        await db.commit()

    print(f"✅ [RESET-TO-NEW] Reset {count} tickets to 'new' status")
    return {"success": True, "count": count, "message": f"Reset {count} tickets to 'new' status"}


@app.get("/support/stats")
async def get_support_stats(user: dict = Depends(get_current_user)):
    """Get support dashboard statistics with detailed analytics"""
    if not DB_SERVICE_AVAILABLE:
        return {"pending": 0, "draft_ready": 0, "approved": 0, "sent": 0, "total": 0}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail
    from sqlalchemy import select, func, and_
    from datetime import datetime, timedelta

    async with get_db() as db:
        # Count by status
        result = await db.execute(
            select(SupportEmail.status, func.count(SupportEmail.id))
            .group_by(SupportEmail.status)
        )
        counts = {row[0]: row[1] for row in result.all()}

        # Classification breakdown
        class_result = await db.execute(
            select(SupportEmail.classification, func.count(SupportEmail.id))
            .group_by(SupportEmail.classification)
        )
        classification_counts = {row[0] or 'unknown': row[1] for row in class_result.all()}

        # Priority breakdown
        priority_result = await db.execute(
            select(SupportEmail.priority, func.count(SupportEmail.id))
            .group_by(SupportEmail.priority)
        )
        priority_counts = {row[0] or 'medium': row[1] for row in priority_result.all()}

        # Intent breakdown
        intent_result = await db.execute(
            select(SupportEmail.intent, func.count(SupportEmail.id))
            .where(SupportEmail.intent.isnot(None))
            .group_by(SupportEmail.intent)
        )
        intent_counts = {row[0]: row[1] for row in intent_result.all()}

        # Sales opportunities count
        sales_result = await db.execute(
            select(func.count(SupportEmail.id))
            .where(SupportEmail.sales_opportunity == True)
        )
        sales_opportunities = sales_result.scalar() or 0

        # Today's emails
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        yesterday_start = today_start - timedelta(days=1)
        week_ago = today_start - timedelta(days=7)

        today_result = await db.execute(
            select(func.count(SupportEmail.id))
            .where(SupportEmail.received_at >= today_start)
        )
        today_count = today_result.scalar() or 0

        yesterday_result = await db.execute(
            select(func.count(SupportEmail.id))
            .where(and_(
                SupportEmail.received_at >= yesterday_start,
                SupportEmail.received_at < today_start
            ))
        )
        yesterday_count = yesterday_result.scalar() or 0

        # Last 7 days
        week_result = await db.execute(
            select(func.count(SupportEmail.id))
            .where(SupportEmail.received_at >= week_ago)
        )
        week_count = week_result.scalar() or 0

        # Average AI confidence
        conf_result = await db.execute(
            select(func.avg(SupportEmail.ai_confidence))
            .where(SupportEmail.ai_confidence.isnot(None))
        )
        avg_confidence = conf_result.scalar()

        # Resolution rate (sent / (sent + rejected))
        sent_count = counts.get("sent", 0)
        rejected_count = counts.get("rejected", 0)
        resolved_total = sent_count + rejected_count
        resolution_rate = round(sent_count / resolved_total * 100, 1) if resolved_total > 0 else 0

        # Draft generation rate (draft_ready / total that have been processed)
        draft_ready = counts.get("draft_ready", 0)
        processed = draft_ready + sent_count + rejected_count + counts.get("approved", 0)
        draft_rate = round(processed / sum(counts.values()) * 100, 1) if sum(counts.values()) > 0 else 0

        return {
            # Status counts
            "pending": counts.get("pending", 0),
            "draft_ready": draft_ready,
            "approved": counts.get("approved", 0),
            "sent": sent_count,
            "rejected": rejected_count,
            "total": sum(counts.values()),

            # Analytics
            "classification_breakdown": classification_counts,
            "priority_breakdown": priority_counts,
            "intent_breakdown": intent_counts,
            "sales_opportunities": sales_opportunities,

            # Time-based metrics
            "today_count": today_count,
            "yesterday_count": yesterday_count,
            "week_count": week_count,

            # Performance metrics
            "avg_confidence": round(float(avg_confidence), 2) if avg_confidence else None,
            "resolution_rate": resolution_rate,
            "ai_draft_rate": draft_rate
        }


@app.get("/support/tickets")
async def get_support_tickets(
    status: Optional[str] = None,
    inbox_type: Optional[str] = None,
    limit: int = 100,
    user: dict = Depends(get_current_user)
):
    """
    Get support tickets grouped by customer email.
    Returns one ticket per customer with aggregated info for manager decision-making.
    """
    if not DB_SERVICE_AVAILABLE:
        return {"tickets": [], "total": 0}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage
    from sqlalchemy import select, func, desc, and_

    if not is_db_configured():
        return {"tickets": [], "total": 0}

    async with get_db() as db:
        # First, get distinct customers with their latest email info
        # Subquery to get the latest email per customer
        latest_subq = (
            select(
                SupportEmail.customer_email,
                func.max(SupportEmail.received_at).label('latest_received'),
            )
            .group_by(SupportEmail.customer_email)
        ).subquery()

        # Build filter conditions
        filters = []
        if inbox_type and inbox_type != 'all':
            filters.append(SupportEmail.inbox_type == inbox_type)
        # Only show customer emails by default (hide suppliers and unclassified)
        filters.append(SupportEmail.sender_type == 'customer')

        # Get customer tickets with aggregated data
        query = (
            select(
                SupportEmail.customer_email,
                SupportEmail.customer_name,
                func.count(SupportEmail.id).label('message_count'),
                func.max(SupportEmail.received_at).label('last_activity'),
                func.min(SupportEmail.received_at).label('first_contact'),
                # Get the status of the most recent email
                func.max(SupportEmail.id).label('latest_email_id'),
            )
            .where(and_(*filters) if filters else True)
            .group_by(SupportEmail.customer_email, SupportEmail.customer_name)
            .order_by(desc(func.max(SupportEmail.received_at)))
            .limit(limit)
        )

        result = await db.execute(query)
        customer_groups = result.all()

        tickets = []
        for row in customer_groups:
            # Get the latest email details for this customer
            latest_email_result = await db.execute(
                select(SupportEmail)
                .where(SupportEmail.id == row.latest_email_id)
            )
            latest_email = latest_email_result.scalar_one_or_none()

            if not latest_email:
                continue

            # Apply status filter if specified
            if status and status != 'all':
                # Get all emails for this customer to check if any match the status
                emails_result = await db.execute(
                    select(SupportEmail)
                    .where(and_(
                        SupportEmail.customer_email == row.customer_email,
                        SupportEmail.status == status
                    ))
                )
                if not emails_result.scalars().first():
                    continue

            # Get all messages for this customer to build conversation summary
            messages_result = await db.execute(
                select(SupportMessage)
                .join(SupportEmail)
                .where(SupportEmail.customer_email == row.customer_email)
                .order_by(SupportMessage.created_at)
            )
            messages = messages_result.scalars().all()

            # Get all email threads for this customer
            emails_result = await db.execute(
                select(SupportEmail)
                .where(SupportEmail.customer_email == row.customer_email)
                .order_by(desc(SupportEmail.received_at))
            )
            customer_emails = emails_result.scalars().all()

            # Determine overall ticket status
            # Only mark as resolved if explicitly resolved with a resolution type
            statuses = [e.status for e in customer_emails]
            resolutions = [e.resolution for e in customer_emails if e.resolution]

            if resolutions:
                # Has explicit resolution - ticket is resolved
                ticket_status = 'resolved'
            elif 'pending' in statuses or 'draft_ready' in statuses:
                # Has pending or draft - needs attention
                ticket_status = 'needs_attention'
            elif 'sent' in statuses or 'approved' in statuses:
                # Response sent, awaiting customer reply
                ticket_status = 'awaiting_reply'
            else:
                ticket_status = latest_email.status

            # Check if there's an AI draft waiting
            has_draft = any(m.ai_draft for m in messages)

            # Get unique intents and subjects
            intents = list(set(e.intent for e in customer_emails if e.intent))
            subjects = list(set(e.subject for e in customer_emails if e.subject))

            # Get the resolution from the most recent resolved email
            resolution = next((e.resolution for e in customer_emails if e.resolution), None)

            tickets.append({
                "customer_email": row.customer_email,
                "customer_name": row.customer_name or row.customer_email.split('@')[0],
                "message_count": row.message_count,
                "thread_count": len(customer_emails),
                "last_activity": row.last_activity.isoformat() if row.last_activity else None,
                "first_contact": row.first_contact.isoformat() if row.first_contact else None,
                "ticket_status": ticket_status,
                "resolution": resolution,
                "has_pending_draft": has_draft and latest_email.status == 'draft_ready',
                "latest_subject": latest_email.subject,
                "latest_status": latest_email.status,
                "latest_email_id": latest_email.id,
                "inbox_type": latest_email.inbox_type,
                "classification": latest_email.classification,
                "priority": latest_email.priority,
                "intents": intents[:3],  # Top 3 intents
                "order_number": latest_email.order_number,
                "tracking_number": latest_email.tracking_number,
                "tracking_status": latest_email.tracking_status,
            })

        return {
            "tickets": tickets,
            "total": len(tickets)
        }


@app.get("/support/customer/{email}/details")
async def get_customer_support_details(email: str, user: dict = Depends(get_current_user)):
    """
    Get complete support history for a customer including all conversations,
    tracking info, and order details for manager decision-making.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage, ShipmentTracking
    from sqlalchemy import select, desc
    import urllib.parse

    if not is_db_configured():
        raise HTTPException(status_code=503, detail="Database not configured")

    decoded_email = urllib.parse.unquote(email)

    async with get_db() as db:
        # Get all email threads for this customer
        emails_result = await db.execute(
            select(SupportEmail)
            .where(SupportEmail.customer_email == decoded_email)
            .order_by(desc(SupportEmail.received_at))
        )
        emails = emails_result.scalars().all()

        if not emails:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Get all messages across all threads
        all_messages = []
        for email_thread in emails:
            messages_result = await db.execute(
                select(SupportMessage)
                .where(SupportMessage.email_id == email_thread.id)
                .order_by(SupportMessage.created_at)
            )
            messages = messages_result.scalars().all()
            for msg in messages:
                all_messages.append({
                    "id": msg.id,
                    "email_id": email_thread.id,
                    "thread_subject": email_thread.subject,
                    "direction": msg.direction,
                    "sender_email": msg.sender_email,
                    "sender_name": msg.sender_name,
                    "content": msg.content,
                    "ai_draft": msg.ai_draft,
                    "final_content": msg.final_content,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
                })

        # Sort all messages chronologically
        all_messages.sort(key=lambda x: x['created_at'] or '')

        # Get tracking info for this customer
        tracking_result = await db.execute(
            select(ShipmentTracking)
            .where(ShipmentTracking.customer_email == decoded_email)
            .order_by(desc(ShipmentTracking.shipped_at))
            .limit(10)
        )
        trackings = tracking_result.scalars().all()

        # Build conversation threads organized by subject/intent
        threads = []
        for email_thread in emails:
            thread_messages = [m for m in all_messages if m['email_id'] == email_thread.id]
            threads.append({
                "id": email_thread.id,
                "thread_id": email_thread.thread_id,
                "subject": email_thread.subject,
                "status": email_thread.status,
                "classification": email_thread.classification,
                "intent": email_thread.intent,
                "priority": email_thread.priority,
                "received_at": email_thread.received_at.isoformat() if email_thread.received_at else None,
                "order_number": email_thread.order_number,
                "resolution": email_thread.resolution,
                "resolution_notes": email_thread.resolution_notes,
                "messages": thread_messages,
            })

        # Get the latest email that needs attention (pending or draft_ready)
        needs_attention = next(
            (e for e in emails if e.status in ['pending', 'draft_ready']),
            emails[0] if emails else None
        )

        return {
            "customer_email": decoded_email,
            "customer_name": emails[0].customer_name if emails else None,
            "total_threads": len(emails),
            "total_messages": len(all_messages),
            "first_contact": min(e.received_at for e in emails).isoformat() if emails else None,
            "last_activity": max(e.received_at for e in emails).isoformat() if emails else None,
            "current_status": needs_attention.status if needs_attention else 'resolved',
            "current_email_id": needs_attention.id if needs_attention else None,
            "threads": threads,
            "all_messages": all_messages,  # Chronological conversation view
            "trackings": [
                {
                    "id": t.id,
                    "tracking_number": t.tracking_number,
                    "carrier": t.carrier,
                    "status": t.status,
                    "status_detail": t.status_detail,
                    "order_number": t.order_number,
                    "shipped_at": t.shipped_at.isoformat() if t.shipped_at else None,
                    "delivered_at": t.delivered_at.isoformat() if t.delivered_at else None,
                    "estimated_delivery": t.estimated_delivery.isoformat() if t.estimated_delivery else None,
                    "last_checkpoint": t.last_checkpoint,
                    "last_checked": t.last_checked.isoformat() if t.last_checked else None,
                    "delay_detected": t.delay_detected,
                }
                for t in trackings
            ],
            # Summary for manager
            "summary": {
                "has_pending_response": needs_attention.status in ['pending', 'draft_ready'] if needs_attention else False,
                "pending_draft": next(
                    (m['ai_draft'] for m in all_messages if m['ai_draft'] and not m['sent_at']),
                    None
                ),
                "order_numbers": list(set(e.order_number for e in emails if e.order_number)),
                "tracking_numbers": list(set(t.tracking_number for t in trackings)),
                "open_issues": [
                    {
                        "subject": e.subject,
                        "intent": e.intent,
                        "status": e.status,
                    }
                    for e in emails
                    if e.status in ['pending', 'draft_ready']
                ],
            }
        }


@app.get("/support/recent-trackings")
async def get_recent_trackings(limit: int = 10, user: dict = Depends(get_current_user)):
    """
    Get recent tracking information for the support dashboard.
    Shows the last N trackings with their current status.
    """
    if not DB_SERVICE_AVAILABLE:
        return {"trackings": []}

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select, desc

    if not is_db_configured():
        return {"trackings": []}

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking)
            .order_by(desc(ShipmentTracking.last_checked))
            .limit(limit)
        )
        trackings = result.scalars().all()

        return {
            "trackings": [
                {
                    "id": t.id,
                    "tracking_number": t.tracking_number,
                    "carrier": t.carrier,
                    "status": t.status,
                    "status_detail": t.status_detail,
                    "customer_email": t.customer_email,
                    "customer_name": t.customer_name,
                    "order_number": t.order_number,
                    "shipped_at": t.shipped_at.isoformat() if t.shipped_at else None,
                    "delivered_at": t.delivered_at.isoformat() if t.delivered_at else None,
                    "estimated_delivery": t.estimated_delivery.isoformat() if t.estimated_delivery else None,
                    "last_checkpoint": t.last_checkpoint,
                    "last_checked": t.last_checked.isoformat() if t.last_checked else None,
                    "delay_detected": t.delay_detected,
                    "delay_days": t.delay_days,
                }
                for t in trackings
            ]
        }


# ==================== ACTIVITY CENTER ====================

@app.get("/support/activity-log")
async def get_activity_log(
    days: int = 7,
    activity_type: str = "all",
    user: dict = Depends(get_current_user)
):
    """
    Get activity log for manager review.
    Shows resolved tickets, sent emails, and sent followups.
    """
    if not DB_SERVICE_AVAILABLE:
        return {"activities": [], "summary": {}}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage, ShipmentTracking, User
    from sqlalchemy import select, desc, func, and_, or_
    from datetime import datetime, timedelta

    if not is_db_configured():
        return {"activities": [], "summary": {}}

    cutoff = datetime.utcnow() - timedelta(days=days)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    async with get_db() as db:
        activities = []

        # 1. Get resolved tickets
        if activity_type in ["all", "resolved"]:
            resolved_query = (
                select(SupportEmail, User)
                .outerjoin(User, SupportEmail.resolved_by == User.id)
                .where(
                    and_(
                        SupportEmail.resolution.isnot(None),
                        SupportEmail.resolved_at >= cutoff
                    )
                )
                .order_by(desc(SupportEmail.resolved_at))
                .limit(100)
            )
            resolved_result = await db.execute(resolved_query)
            for email, agent in resolved_result:
                activities.append({
                    "id": f"resolved_{email.id}",
                    "type": "resolved",
                    "timestamp": email.resolved_at.isoformat() if email.resolved_at else None,
                    "customer_email": email.customer_email,
                    "customer_name": email.customer_name,
                    "subject": email.subject,
                    "action": email.resolution,
                    "details": email.resolution_notes,
                    "agent": agent.name if agent else "System",
                    "order_number": email.order_number,
                })

        # 2. Get sent support replies
        if activity_type in ["all", "sent"]:
            sent_query = (
                select(SupportMessage, SupportEmail, User)
                .join(SupportEmail, SupportMessage.email_id == SupportEmail.id)
                .outerjoin(User, SupportMessage.approved_by == User.id)
                .where(
                    and_(
                        SupportMessage.sent_at.isnot(None),
                        SupportMessage.sent_at >= cutoff,
                        SupportMessage.direction == "outbound"
                    )
                )
                .order_by(desc(SupportMessage.sent_at))
                .limit(100)
            )
            sent_result = await db.execute(sent_query)
            for msg, email, agent in sent_result:
                content = msg.final_content or msg.ai_draft or ""
                activities.append({
                    "id": f"sent_{msg.id}",
                    "type": "sent_reply",
                    "timestamp": msg.sent_at.isoformat() if msg.sent_at else None,
                    "customer_email": email.customer_email,
                    "customer_name": email.customer_name,
                    "subject": f"RE: {email.subject}",
                    "action": "sent",
                    "details": content[:200] + "..." if len(content) > 200 else content,
                    "agent": agent.name if agent else "System",
                    "ticket_id": email.id,
                })

        # 3. Get sent delivery followups
        if activity_type in ["all", "followup"]:
            followup_query = (
                select(ShipmentTracking)
                .where(
                    and_(
                        ShipmentTracking.followup_status == "sent",
                        ShipmentTracking.delivered_at >= cutoff
                    )
                )
                .order_by(desc(ShipmentTracking.delivered_at))
                .limit(100)
            )
            followup_result = await db.execute(followup_query)
            for tracking in followup_result.scalars():
                activities.append({
                    "id": f"followup_{tracking.id}",
                    "type": "followup_sent",
                    "timestamp": tracking.delivered_at.isoformat() if tracking.delivered_at else None,
                    "customer_email": tracking.customer_email,
                    "customer_name": tracking.customer_name,
                    "subject": tracking.followup_draft_subject or "Delivery followup",
                    "action": "followup_sent",
                    "details": (tracking.followup_draft_body[:200] + "...") if tracking.followup_draft_body and len(tracking.followup_draft_body) > 200 else tracking.followup_draft_body,
                    "agent": "System",
                    "order_number": tracking.order_number,
                })

        # Sort all activities by timestamp
        activities.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        # Get summary counts
        resolved_today = await db.execute(
            select(func.count(SupportEmail.id))
            .where(and_(SupportEmail.resolved_at >= today_start, SupportEmail.resolution.isnot(None)))
        )
        sent_today = await db.execute(
            select(func.count(SupportMessage.id))
            .where(and_(SupportMessage.sent_at >= today_start, SupportMessage.direction == "outbound"))
        )
        followups_today = await db.execute(
            select(func.count(ShipmentTracking.id))
            .where(and_(ShipmentTracking.followup_status == "sent", ShipmentTracking.delivered_at >= today_start))
        )

        return {
            "activities": activities[:100],
            "summary": {
                "resolved_today": resolved_today.scalar() or 0,
                "sent_today": sent_today.scalar() or 0,
                "followups_today": followups_today.scalar() or 0,
            }
        }


@app.get("/support/resolution-stats")
async def get_resolution_stats(
    days: int = 30,
    user: dict = Depends(get_current_user)
):
    """
    Get resolution statistics for manager review.
    Shows resolution type breakdown, response times, and agent performance.
    """
    if not DB_SERVICE_AVAILABLE:
        return {}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, User
    from sqlalchemy import select, func, and_, case
    from datetime import datetime, timedelta

    if not is_db_configured():
        return {}

    cutoff = datetime.utcnow() - timedelta(days=days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    two_weeks_ago = datetime.utcnow() - timedelta(days=14)

    async with get_db() as db:
        # Total resolved in period
        total_resolved = await db.execute(
            select(func.count(SupportEmail.id))
            .where(and_(SupportEmail.resolved_at >= cutoff, SupportEmail.resolution.isnot(None)))
        )
        total_resolved_count = total_resolved.scalar() or 0

        # Total tickets in period
        total_tickets = await db.execute(
            select(func.count(SupportEmail.id))
            .where(SupportEmail.received_at >= cutoff)
        )
        total_tickets_count = total_tickets.scalar() or 0

        # Resolution rate
        resolution_rate = total_resolved_count / total_tickets_count if total_tickets_count > 0 else 0

        # Avg resolution time
        avg_resolution = await db.execute(
            select(func.avg(SupportEmail.resolution_time_minutes))
            .where(and_(SupportEmail.resolved_at >= cutoff, SupportEmail.resolution_time_minutes.isnot(None)))
        )
        avg_resolution_time = avg_resolution.scalar() or 0

        # Avg first response time
        avg_response = await db.execute(
            select(func.avg(SupportEmail.response_time_minutes))
            .where(and_(SupportEmail.received_at >= cutoff, SupportEmail.response_time_minutes.isnot(None)))
        )
        avg_response_time = avg_response.scalar() or 0

        # Resolution type breakdown
        resolution_breakdown = await db.execute(
            select(SupportEmail.resolution, func.count(SupportEmail.id))
            .where(and_(SupportEmail.resolved_at >= cutoff, SupportEmail.resolution.isnot(None)))
            .group_by(SupportEmail.resolution)
        )
        by_resolution_type = {row[0]: row[1] for row in resolution_breakdown}

        # Agent performance
        agent_stats = await db.execute(
            select(
                User.id,
                User.name,
                func.count(SupportEmail.id).label("resolved"),
                func.avg(SupportEmail.resolution_time_minutes).label("avg_time")
            )
            .join(SupportEmail, SupportEmail.resolved_by == User.id)
            .where(and_(SupportEmail.resolved_at >= cutoff, SupportEmail.resolution.isnot(None)))
            .group_by(User.id, User.name)
            .order_by(func.count(SupportEmail.id).desc())
        )
        by_agent = [
            {"agent_id": row[0], "agent_name": row[1], "resolved": row[2], "avg_time": int(row[3] or 0)}
            for row in agent_stats
        ]

        # Trend: this week vs last week
        this_week = await db.execute(
            select(func.count(SupportEmail.id))
            .where(and_(SupportEmail.resolved_at >= week_ago, SupportEmail.resolution.isnot(None)))
        )
        last_week = await db.execute(
            select(func.count(SupportEmail.id))
            .where(and_(
                SupportEmail.resolved_at >= two_weeks_ago,
                SupportEmail.resolved_at < week_ago,
                SupportEmail.resolution.isnot(None)
            ))
        )
        this_week_count = this_week.scalar() or 0
        last_week_count = last_week.scalar() or 0
        change_pct = ((this_week_count - last_week_count) / last_week_count * 100) if last_week_count > 0 else 0

        return {
            "total_resolved": total_resolved_count,
            "total_tickets": total_tickets_count,
            "resolution_rate": round(resolution_rate, 2),
            "avg_resolution_time_minutes": int(avg_resolution_time),
            "avg_first_response_minutes": int(avg_response_time),
            "by_resolution_type": by_resolution_type,
            "by_agent": by_agent,
            "trend": {
                "this_week": this_week_count,
                "last_week": last_week_count,
                "change_pct": round(change_pct, 1)
            }
        }


@app.get("/support/sent-emails")
async def get_sent_emails(
    days: int = 7,
    email_type: str = "all",
    user: dict = Depends(get_current_user)
):
    """
    Get all sent emails from the system.
    Includes support replies and delivery followups.
    """
    if not DB_SERVICE_AVAILABLE:
        return {"emails": [], "total_sent": 0, "by_type": {}}

    from database.connection import get_db, is_db_configured
    from database.models import SupportEmail, SupportMessage, ShipmentTracking, User
    from sqlalchemy import select, desc, func, and_
    from datetime import datetime, timedelta

    if not is_db_configured():
        return {"emails": [], "total_sent": 0, "by_type": {}}

    cutoff = datetime.utcnow() - timedelta(days=days)

    async with get_db() as db:
        emails = []

        # 1. Get sent support replies
        if email_type in ["all", "support"]:
            sent_query = (
                select(SupportMessage, SupportEmail, User)
                .join(SupportEmail, SupportMessage.email_id == SupportEmail.id)
                .outerjoin(User, SupportMessage.approved_by == User.id)
                .where(
                    and_(
                        SupportMessage.sent_at.isnot(None),
                        SupportMessage.sent_at >= cutoff,
                        SupportMessage.direction == "outbound"
                    )
                )
                .order_by(desc(SupportMessage.sent_at))
                .limit(200)
            )
            sent_result = await db.execute(sent_query)
            for msg, email, agent in sent_result:
                content = msg.final_content or msg.ai_draft or ""
                emails.append({
                    "id": msg.id,
                    "type": "support_reply",
                    "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
                    "to_email": email.customer_email,
                    "to_name": email.customer_name,
                    "subject": f"RE: {email.subject}",
                    "preview": content[:150] + "..." if len(content) > 150 else content,
                    "approved_by": agent.name if agent else None,
                    "ticket_id": email.id,
                })

        # 2. Get sent delivery followups
        if email_type in ["all", "followup"]:
            followup_query = (
                select(ShipmentTracking)
                .where(
                    and_(
                        ShipmentTracking.followup_status == "sent",
                        ShipmentTracking.delivered_at >= cutoff
                    )
                )
                .order_by(desc(ShipmentTracking.delivered_at))
                .limit(200)
            )
            followup_result = await db.execute(followup_query)
            for tracking in followup_result.scalars():
                body = tracking.followup_draft_body or ""
                emails.append({
                    "id": tracking.id,
                    "type": "delivery_followup",
                    "sent_at": tracking.delivered_at.isoformat() if tracking.delivered_at else None,
                    "to_email": tracking.customer_email,
                    "to_name": tracking.customer_name,
                    "subject": tracking.followup_draft_subject or "Delivery followup",
                    "preview": body[:150] + "..." if len(body) > 150 else body,
                    "order_number": tracking.order_number,
                })

        # Sort by sent_at
        emails.sort(key=lambda x: x.get("sent_at") or "", reverse=True)

        # Count by type
        support_count = len([e for e in emails if e["type"] == "support_reply"])
        followup_count = len([e for e in emails if e["type"] == "delivery_followup"])

        return {
            "emails": emails[:100],
            "total_sent": len(emails),
            "by_type": {
                "support_reply": support_count,
                "delivery_followup": followup_count
            }
        }


# ==================== TRACKING DASHBOARD ====================

@app.get("/tracking/shipments")
async def list_shipments(
    status: Optional[str] = None,
    delayed_only: bool = False,
    followup_pending: bool = False,
    limit: int = 100,
    user: dict = Depends(get_current_user)
):
    """List all tracked shipments with status."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select, desc

    if not is_db_configured():
        raise HTTPException(status_code=503, detail="Database not configured")

    async with get_db() as db:
        query = select(ShipmentTracking).order_by(desc(ShipmentTracking.shipped_at))

        if status:
            query = query.where(ShipmentTracking.status == status)
        if delayed_only:
            query = query.where(ShipmentTracking.delay_detected == True)
        if followup_pending:
            query = query.where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivery_followup_sent == False
            )

        query = query.limit(limit)
        result = await db.execute(query)
        shipments = result.scalars().all()

        return {
            "shipments": [
                {
                    "id": s.id,
                    "order_id": s.order_id,
                    "order_number": s.order_number,
                    "customer_email": s.customer_email,
                    "customer_name": s.customer_name,
                    "tracking_number": s.tracking_number,
                    "carrier": s.carrier,
                    "status": s.status,
                    "status_detail": s.status_detail,
                    "last_checkpoint": s.last_checkpoint,
                    "last_checkpoint_time": s.last_checkpoint_time.isoformat() if s.last_checkpoint_time else None,
                    "shipped_at": s.shipped_at.isoformat() if s.shipped_at else None,
                    "estimated_delivery": s.estimated_delivery.isoformat() if s.estimated_delivery else None,
                    "delivered_at": s.delivered_at.isoformat() if s.delivered_at else None,
                    "delay_detected": s.delay_detected,
                    "delay_days": s.delay_days,
                    "delivery_followup_sent": s.delivery_followup_sent,
                    "last_checked": s.last_checked.isoformat() if s.last_checked else None,
                }
                for s in shipments
            ],
            "total": len(shipments)
        }


@app.get("/tracking/stats")
async def get_tracking_stats(user: dict = Depends(get_current_user)):
    """Get tracking dashboard statistics."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select, func

    if not is_db_configured():
        raise HTTPException(status_code=503, detail="Database not configured")

    async with get_db() as db:
        # Count by status
        status_query = select(
            ShipmentTracking.status,
            func.count(ShipmentTracking.id)
        ).group_by(ShipmentTracking.status)
        status_result = await db.execute(status_query)
        status_counts = dict(status_result.all())

        # Count delayed
        delayed_result = await db.execute(
            select(func.count(ShipmentTracking.id))
            .where(ShipmentTracking.delay_detected == True)
        )
        delayed_count = delayed_result.scalar() or 0

        # Count pending followups
        followup_result = await db.execute(
            select(func.count(ShipmentTracking.id))
            .where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivery_followup_sent == False
            )
        )
        followup_pending = followup_result.scalar() or 0

        # Average delivery time for delivered packages
        avg_delivery_result = await db.execute(
            select(func.avg(
                func.extract('epoch', ShipmentTracking.delivered_at) -
                func.extract('epoch', ShipmentTracking.shipped_at)
            ) / 86400)  # Convert seconds to days
            .where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivered_at.isnot(None),
                ShipmentTracking.shipped_at.isnot(None)
            )
        )
        avg_delivery_days = avg_delivery_result.scalar()

        # Count followups sent
        followup_sent_result = await db.execute(
            select(func.count(ShipmentTracking.id))
            .where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivery_followup_sent == True
            )
        )
        followup_sent = followup_sent_result.scalar() or 0

        # Stats by destination country (top 5)
        country_result = await db.execute(
            select(
                ShipmentTracking.delivery_address_country,
                func.count(ShipmentTracking.id)
            )
            .where(ShipmentTracking.delivery_address_country.isnot(None))
            .group_by(ShipmentTracking.delivery_address_country)
            .order_by(func.count(ShipmentTracking.id).desc())
            .limit(5)
        )
        by_country = [{"country": c, "count": n} for c, n in country_result.all() if c]

        # Stats by carrier
        carrier_result = await db.execute(
            select(
                ShipmentTracking.carrier,
                func.count(ShipmentTracking.id)
            )
            .where(ShipmentTracking.carrier.isnot(None))
            .group_by(ShipmentTracking.carrier)
            .order_by(func.count(ShipmentTracking.id).desc())
            .limit(5)
        )
        by_carrier = [{"carrier": c or "Unknown", "count": n} for c, n in carrier_result.all()]

        # Active shipments (in transit + out for delivery)
        active_count = status_counts.get("in_transit", 0) + status_counts.get("out_for_delivery", 0) + status_counts.get("pending", 0)

        # Calculate delivery rate
        total = sum(status_counts.values())
        delivered = status_counts.get("delivered", 0)
        delivery_rate = round((delivered / total) * 100, 1) if total > 0 else 0

        # Count drafts ready for approval
        drafts_ready_result = await db.execute(
            select(func.count(ShipmentTracking.id))
            .where(
                ShipmentTracking.followup_status == "draft_ready",
                ShipmentTracking.delivery_followup_sent == False
            )
        )
        drafts_ready = drafts_ready_result.scalar() or 0

        return {
            "total": total,
            "pending": status_counts.get("pending", 0),
            "in_transit": status_counts.get("in_transit", 0),
            "out_for_delivery": status_counts.get("out_for_delivery", 0),
            "delivered": delivered,
            "exception": status_counts.get("exception", 0),
            "delayed": delayed_count,
            "followup_pending": followup_pending,
            "followup_sent": followup_sent,
            "drafts_ready": drafts_ready,
            "avg_delivery_days": round(avg_delivery_days, 1) if avg_delivery_days else None,
            "delivery_rate": delivery_rate,
            "active_shipments": active_count,
            "by_country": by_country,
            "by_carrier": by_carrier,
        }


@app.post("/tracking/sync")
async def sync_shipments_from_shopify(user: dict = Depends(get_current_user)):
    """Sync shipments from Shopify fulfillments."""
    print(f"🚚 [SYNC] Starting Shopify sync, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [SYNC] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    if not is_db_configured():
        print(f"❌ [SYNC] Database not configured")
        raise HTTPException(status_code=503, detail="Database not configured")

    shopify_store = os.getenv("SHOPIFY_STORE")
    shopify_token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")

    print(f"🚚 [SYNC] Shopify store: {shopify_store}, token: {'set' if shopify_token else 'missing'}")

    if not shopify_store or not shopify_token:
        print(f"❌ [SYNC] Missing Shopify credentials")
        raise HTTPException(
            status_code=500,
            detail=f"Shopify credentials not configured. SHOPIFY_STORE={'set' if shopify_store else 'missing'}, TOKEN={'set' if shopify_token else 'missing'}"
        )

    # Import tracking service
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from tracking_service import sync_shipments_from_shopify as sync_shopify, check_tracking_aftership
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Tracking service import failed: {e}")

    try:
        # Sync from Shopify
        shopify_shipments = sync_shopify(shopify_store, shopify_token, days_back=30)

        synced = 0
        updated = 0

        async with get_db() as db:
            for shipment in shopify_shipments:
                # Check if already exists
                result = await db.execute(
                    select(ShipmentTracking)
                    .where(ShipmentTracking.tracking_number == shipment["tracking_number"])
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update if needed
                    updated += 1
                else:
                    # Create new - parse shipped_at and convert to naive UTC datetime
                    shipped_at_value = None
                    if shipment.get("shipped_at"):
                        shipped_dt = datetime.fromisoformat(shipment["shipped_at"].replace("Z", "+00:00"))
                        # Convert to UTC naive datetime for database
                        if shipped_dt.tzinfo:
                            shipped_at_value = shipped_dt.astimezone(pytz.UTC).replace(tzinfo=None)
                        else:
                            shipped_at_value = shipped_dt

                    new_shipment = ShipmentTracking(
                        order_id=shipment.get("order_id"),
                        order_number=shipment.get("order_number"),
                        customer_email=shipment.get("customer_email"),
                        customer_name=shipment.get("customer_name"),
                        tracking_number=shipment.get("tracking_number"),
                        carrier=shipment.get("carrier"),
                        shipped_at=shipped_at_value,
                        delivery_address_city=shipment.get("delivery_address_city"),
                        delivery_address_country=shipment.get("delivery_address_country"),
                        status="pending",
                    )
                    db.add(new_shipment)
                    synced += 1

            await db.commit()

        print(f"✅ [SYNC] Completed: synced={synced}, updated={updated}, total_from_shopify={len(shopify_shipments)}")
        return {
            "success": True,
            "synced": synced,
            "updated": updated,
            "total_from_shopify": len(shopify_shipments)
        }
    except Exception as e:
        import traceback
        print(f"❌ [SYNC] Failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}\n{traceback.format_exc()}")


@app.post("/tracking/check/{tracking_number}")
async def check_single_tracking(tracking_number: str, user: dict = Depends(get_current_user)):
    """Check tracking status for a single package via AfterShip."""
    print(f"🚚 [CHECK] Checking tracking {tracking_number}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [CHECK] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    if not is_db_configured():
        print(f"❌ [CHECK] Database not configured")
        raise HTTPException(status_code=503, detail="Database not configured")

    # Import tracking service
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from tracking_service import check_tracking_aftership, detect_delays
    except ImportError as e:
        print(f"❌ [CHECK] Tracking service import failed: {e}")
        raise HTTPException(status_code=500, detail="Tracking service not available")

    # Get from AfterShip (always verbose for debugging)
    print(f"🚚 [CHECK] Calling AfterShip API for {tracking_number}...")
    result = check_tracking_aftership(tracking_number, verbose=True)

    if not result.get("success"):
        error = result.get("error", "Unknown error")
        # Check if rate limited
        if result.get("rate_limited") or error == "rate_limit":
            print(f"⚠️ [CHECK] Rate limited for {tracking_number}")
            return {
                "success": False,
                "error": "rate_limit",
                "message": result.get("message", "AfterShip API limit reached. Try again later."),
                "rate_limited": True
            }
        return {"success": False, "error": error}

    # Update database if exists
    async with get_db() as db:
        db_result = await db.execute(
            select(ShipmentTracking)
            .where(ShipmentTracking.tracking_number == tracking_number)
        )
        shipment = db_result.scalar_one_or_none()

        if shipment:
            shipment.status = result.get("status", "unknown")
            shipment.status_detail = result.get("status_detail")
            shipment.last_checkpoint = result.get("last_checkpoint")
            if result.get("last_checkpoint_time"):
                try:
                    dt = datetime.fromisoformat(
                        result["last_checkpoint_time"].replace("Z", "+00:00")
                    )
                    # Convert to naive UTC for database
                    if dt.tzinfo:
                        shipment.last_checkpoint_time = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    else:
                        shipment.last_checkpoint_time = dt
                except:
                    pass
            if result.get("estimated_delivery"):
                try:
                    dt = datetime.fromisoformat(
                        result["estimated_delivery"].replace("Z", "+00:00")
                    )
                    if dt.tzinfo:
                        shipment.estimated_delivery = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    else:
                        shipment.estimated_delivery = dt
                except:
                    pass
            if result.get("delivered_at"):
                try:
                    dt = datetime.fromisoformat(
                        result["delivered_at"].replace("Z", "+00:00")
                    )
                    if dt.tzinfo:
                        shipment.delivered_at = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    else:
                        shipment.delivered_at = dt
                except:
                    pass

            # Check for delays
            delay_info = detect_delays(
                shipment.shipped_at,
                shipment.estimated_delivery,
                result.get("status")
            )
            shipment.delay_detected = delay_info.get("delayed", False)
            shipment.delay_days = delay_info.get("delay_days", 0)

            shipment.last_checked = datetime.utcnow()
            await db.commit()

            # Auto-generate followup draft when delivery is detected (don't auto-send)
            if result.get("status") == "delivered" and not shipment.delivery_followup_sent and shipment.followup_status != 'draft_ready':
                try:
                    import sys
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
                    from followup_service import generate_followup_email

                    # Parse line items
                    ordered_items = []
                    if shipment.line_items:
                        ordered_items = [item.strip() for item in shipment.line_items.split(",") if item.strip()]

                    # Generate draft (don't send)
                    draft = generate_followup_email(
                        customer_name=shipment.customer_name or "",
                        customer_email=shipment.customer_email,
                        order_number=shipment.order_number or "",
                        ordered_items=ordered_items,
                        delivered_date=shipment.delivered_at,
                    )

                    if draft.get("success"):
                        shipment.followup_draft_subject = draft.get("subject")
                        shipment.followup_draft_body = draft.get("body")
                        shipment.followup_draft_generated_at = datetime.utcnow()
                        shipment.followup_status = 'draft_ready'
                        await db.commit()
                        print(f"[tracking] Generated followup draft for {shipment.customer_email} order {shipment.order_number}")
                except Exception as e:
                    print(f"[tracking] Draft generation failed for {shipment.tracking_number}: {e}")

    return {
        "success": True,
        "tracking_number": tracking_number,
        **result
    }


@app.post("/tracking/check-all")
async def check_all_active_trackings(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Queue check for all active (non-delivered) shipments."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking.tracking_number)
            .where(ShipmentTracking.status.notin_(["delivered", "expired"]))
        )
        tracking_numbers = [r[0] for r in result.all()]

    # Queue background check
    background_tasks.add_task(check_trackings_background, tracking_numbers)

    return {
        "success": True,
        "message": f"Checking {len(tracking_numbers)} active shipments in background",
        "count": len(tracking_numbers)
    }


async def check_trackings_background(tracking_numbers: List[str]):
    """Background task to check multiple trackings."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    from tracking_service import check_tracking_aftership, detect_delays
    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select
    import asyncio

    delivered_count = 0
    followup_sent_count = 0

    for tracking_number in tracking_numbers:
        try:
            print(f"[tracking:batch] Checking {tracking_number}...")
            result = check_tracking_aftership(tracking_number, verbose=True)

            if result.get("success"):
                async with get_db() as db:
                    db_result = await db.execute(
                        select(ShipmentTracking)
                        .where(ShipmentTracking.tracking_number == tracking_number)
                    )
                    shipment = db_result.scalar_one_or_none()

                    if shipment:
                        previous_status = shipment.status
                        shipment.status = result.get("status", "unknown")
                        shipment.status_detail = result.get("status_detail")
                        shipment.last_checkpoint = result.get("last_checkpoint")
                        shipment.last_checked = datetime.utcnow()

                        # Update delivered_at if status is delivered
                        if result.get("status") == "delivered":
                            delivered_count += 1
                            if result.get("delivered_at"):
                                try:
                                    shipment.delivered_at = datetime.fromisoformat(
                                        result["delivered_at"].replace("Z", "+00:00")
                                    )
                                except:
                                    shipment.delivered_at = datetime.utcnow()

                        await db.commit()

                        # Auto-generate followup draft when delivery is detected (don't auto-send)
                        if result.get("status") == "delivered" and not shipment.delivery_followup_sent and shipment.followup_status != 'draft_ready':
                            try:
                                from followup_service import generate_followup_email

                                ordered_items = []
                                if shipment.line_items:
                                    ordered_items = [item.strip() for item in shipment.line_items.split(",") if item.strip()]

                                draft = generate_followup_email(
                                    customer_name=shipment.customer_name or "",
                                    customer_email=shipment.customer_email,
                                    order_number=shipment.order_number or "",
                                    ordered_items=ordered_items,
                                    delivered_date=shipment.delivered_at,
                                )

                                if draft.get("success"):
                                    shipment.followup_draft_subject = draft.get("subject")
                                    shipment.followup_draft_body = draft.get("body")
                                    shipment.followup_draft_generated_at = datetime.utcnow()
                                    shipment.followup_status = 'draft_ready'
                                    await db.commit()
                                    followup_sent_count += 1  # Renamed: now counts drafts generated
                                    print(f"[tracking] Generated followup draft for {shipment.customer_email} order {shipment.order_number}")
                            except Exception as e:
                                print(f"[tracking] Draft generation failed for {tracking_number}: {e}")

            # Rate limit - AfterShip has limits
            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"[tracking] Error checking {tracking_number}: {e}")

    print(f"[tracking] Background check complete: {len(tracking_numbers)} checked, {delivered_count} delivered, {followup_sent_count} followups sent")


@app.post("/tracking/mark-followup-sent/{tracking_id}")
async def mark_followup_sent(tracking_id: int, user: dict = Depends(get_current_user)):
    """Mark a delivered shipment as having followup sent."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        shipment.delivery_followup_sent = True
        await db.commit()

    return {"success": True, "message": "Marked as followup sent"}


# ==================== DELIVERY FOLLOWUP SYSTEM ====================

class FollowupPreviewRequest(BaseModel):
    customer_email: str
    customer_name: str
    order_number: str
    ordered_items: List[str]


@app.post("/tracking/followup/preview")
async def preview_followup_email(req: FollowupPreviewRequest, user: dict = Depends(get_current_user)):
    """
    Preview a followup email before sending.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from followup_service import generate_followup_email
    except ImportError:
        raise HTTPException(status_code=500, detail="Followup service not available")

    result = generate_followup_email(
        customer_name=req.customer_name,
        customer_email=req.customer_email,
        order_number=req.order_number,
        ordered_items=req.ordered_items,
    )

    return {
        "success": True,
        "preview": {
            "subject": result.get("subject"),
            "body": result.get("body"),
            "recommendations": result.get("recommendations", []),
        }
    }


@app.post("/tracking/followup/send/{tracking_id}")
async def send_followup_for_shipment(tracking_id: int, user: dict = Depends(get_current_user)):
    """
    Generate and send followup email for a specific delivered shipment.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from followup_service import process_delivery_followup
    except ImportError:
        raise HTTPException(status_code=500, detail="Followup service not available")

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        if shipment.status != "delivered":
            raise HTTPException(status_code=400, detail="Shipment not yet delivered")

        if shipment.delivery_followup_sent:
            raise HTTPException(status_code=400, detail="Followup already sent for this shipment")

        # Get order items from Shopify if we don't have them
        ordered_items = []
        shopify_store = os.getenv("SHOPIFY_STORE")
        shopify_token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")

        if shipment.order_id and shopify_store and shopify_token:
            try:
                import requests
                url = f"https://{shopify_store}/admin/api/2024-01/orders/{shipment.order_id}.json"
                headers = {"X-Shopify-Access-Token": shopify_token}
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code == 200:
                    order_data = response.json().get("order", {})
                    ordered_items = [item.get("title", "") for item in order_data.get("line_items", [])]
            except Exception as e:
                print(f"[followup] Error fetching order items: {e}")

        # If still no items, use generic list
        if not ordered_items:
            ordered_items = ["Korean skincare products"]

        # Process the followup
        followup_result = process_delivery_followup(
            customer_email=shipment.customer_email,
            customer_name=shipment.customer_name or "Customer",
            order_number=shipment.order_number or str(shipment.order_id),
            ordered_items=ordered_items,
            delivered_date=shipment.delivered_at,
            send_email=True,
        )

        if followup_result.get("email_sent"):
            shipment.delivery_followup_sent = True
            await db.commit()

        return {
            "success": followup_result.get("email_sent", False),
            "email": followup_result.get("email_generated", {}),
            "sent": followup_result.get("email_sent", False),
            "error": followup_result.get("send_error"),
        }


@app.post("/tracking/followup/send-all")
async def send_all_pending_followups(
    background_tasks: BackgroundTasks,
    limit: int = 10,
    user: dict = Depends(get_current_user)
):
    """
    Queue sending followup emails for all delivered shipments that haven't had followup sent.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking)
            .where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivery_followup_sent == False,
            )
            .limit(limit)
        )
        pending_shipments = result.scalars().all()

        shipment_ids = [s.id for s in pending_shipments]

    if not shipment_ids:
        return {"success": True, "message": "No pending followups", "count": 0}

    # Queue background task
    background_tasks.add_task(send_followups_background, shipment_ids)

    return {
        "success": True,
        "message": f"Queued {len(shipment_ids)} followup emails",
        "count": len(shipment_ids),
    }


async def send_followups_background(shipment_ids: List[int]):
    """Background task to send multiple followup emails."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    from followup_service import process_delivery_followup
    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select
    import asyncio
    import requests

    shopify_store = os.getenv("SHOPIFY_STORE")
    shopify_token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")

    for shipment_id in shipment_ids:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(ShipmentTracking).where(ShipmentTracking.id == shipment_id)
                )
                shipment = result.scalar_one_or_none()

                if not shipment or shipment.delivery_followup_sent:
                    continue

                # Get order items
                ordered_items = []
                if shipment.order_id and shopify_store and shopify_token:
                    try:
                        url = f"https://{shopify_store}/admin/api/2024-01/orders/{shipment.order_id}.json"
                        headers = {"X-Shopify-Access-Token": shopify_token}
                        response = requests.get(url, headers=headers, timeout=30)
                        if response.status_code == 200:
                            order_data = response.json().get("order", {})
                            ordered_items = [item.get("title", "") for item in order_data.get("line_items", [])]
                    except Exception as e:
                        print(f"[followup] Error fetching order items: {e}")

                if not ordered_items:
                    ordered_items = ["Korean skincare products"]

                # Send followup
                followup_result = process_delivery_followup(
                    customer_email=shipment.customer_email,
                    customer_name=shipment.customer_name or "Customer",
                    order_number=shipment.order_number or str(shipment.order_id),
                    ordered_items=ordered_items,
                    send_email=True,
                )

                if followup_result.get("email_sent"):
                    shipment.delivery_followup_sent = True
                    await db.commit()
                    print(f"[followup] Sent followup for order #{shipment.order_number} to {shipment.customer_email}")

            # Rate limit - don't spam
            await asyncio.sleep(2)

        except Exception as e:
            print(f"[followup] Error processing shipment {shipment_id}: {e}")


@app.get("/tracking/followup/pending")
async def list_pending_followups(limit: int = 50, user: dict = Depends(get_current_user)):
    """
    List all delivered shipments that need followup emails.
    """
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db, is_db_configured
    from database.models import ShipmentTracking
    from sqlalchemy import select, desc

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking)
            .where(
                ShipmentTracking.status == "delivered",
                ShipmentTracking.delivery_followup_sent == False,
            )
            .order_by(desc(ShipmentTracking.delivered_at))
            .limit(limit)
        )
        shipments = result.scalars().all()

        return {
            "pending": [
                {
                    "id": s.id,
                    "order_number": s.order_number,
                    "customer_email": s.customer_email,
                    "customer_name": s.customer_name,
                    "delivered_at": s.delivered_at.isoformat() if s.delivered_at else None,
                    "delivery_address_country": s.delivery_address_country,
                    "line_items": s.line_items,
                    "followup_status": s.followup_status or 'none',
                    "followup_draft_subject": s.followup_draft_subject,
                    "followup_draft_body": s.followup_draft_body,
                    "followup_draft_generated_at": s.followup_draft_generated_at.isoformat() if s.followup_draft_generated_at else None,
                }
                for s in shipments
            ],
            "count": len(shipments),
        }


# ==================== FOLLOWUP APPROVAL WORKFLOW ====================

class RegenerateFollowupRequest(BaseModel):
    instructions: Optional[str] = None  # e.g., "Make it shorter", "Don't mention products"


@app.post("/tracking/followup/generate/{tracking_id}")
async def generate_followup_draft(tracking_id: int, user: dict = Depends(get_current_user)):
    """Generate a followup email draft for approval (without sending)."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import ShipmentTracking
    from sqlalchemy import select

    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from followup_service import generate_followup_email
    except ImportError:
        raise HTTPException(status_code=500, detail="Followup service not available")

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # Parse line items
        ordered_items = []
        if shipment.line_items:
            ordered_items = [item.strip() for item in shipment.line_items.split(",") if item.strip()]
        if not ordered_items:
            ordered_items = ["Korean skincare products"]

        # Generate draft
        draft = generate_followup_email(
            customer_name=shipment.customer_name or "",
            customer_email=shipment.customer_email,
            order_number=shipment.order_number or "",
            ordered_items=ordered_items,
            delivered_date=shipment.delivered_at,
        )

        if draft.get("success"):
            shipment.followup_draft_subject = draft.get("subject")
            shipment.followup_draft_body = draft.get("body")
            shipment.followup_draft_generated_at = datetime.utcnow()
            shipment.followup_status = 'draft_ready'
            await db.commit()

        return {
            "success": True,
            "draft": {
                "subject": shipment.followup_draft_subject,
                "body": shipment.followup_draft_body,
                "generated_at": shipment.followup_draft_generated_at.isoformat() if shipment.followup_draft_generated_at else None,
            },
            "shipment": {
                "id": shipment.id,
                "order_number": shipment.order_number,
                "customer_email": shipment.customer_email,
                "customer_name": shipment.customer_name,
            }
        }


@app.post("/tracking/followup/regenerate/{tracking_id}")
async def regenerate_followup_draft(tracking_id: int, req: RegenerateFollowupRequest, user: dict = Depends(get_current_user)):
    """Regenerate followup email draft with custom instructions."""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import ShipmentTracking
    from sqlalchemy import select
    from openai import OpenAI

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # Parse line items
        ordered_items = []
        if shipment.line_items:
            ordered_items = [item.strip() for item in shipment.line_items.split(",") if item.strip()]
        if not ordered_items:
            ordered_items = ["Korean skincare products"]

        first_name = shipment.customer_name.split()[0] if shipment.customer_name else "there"
        items_text = ", ".join(ordered_items[:3])

        # Build prompt with instructions
        base_prompt = f"""Write a short, warm follow-up email from Emma at Mirai Skin to a customer whose order was just delivered.

Customer: {first_name}
Order: #{shipment.order_number}
Items: {items_text}

Guidelines:
- Be warm and genuine, not salesy
- Ask how they're enjoying their products
- Mention we're here if they have questions about their skincare routine
- Keep it SHORT - 3-4 sentences max
- Sign off as Emma"""

        if req.instructions:
            base_prompt += f"\n\nADDITIONAL INSTRUCTIONS: {req.instructions}"

        base_prompt += "\n\nWrite ONLY the email body, no subject line."

        # Generate with OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": base_prompt}],
                max_tokens=300,
                temperature=0.7,
            )
            body = response.choices[0].message.content.strip()
            subject = f"How are you enjoying your order, {first_name}?"

            shipment.followup_draft_subject = subject
            shipment.followup_draft_body = body
            shipment.followup_draft_generated_at = datetime.utcnow()
            shipment.followup_status = 'draft_ready'
            await db.commit()

            return {
                "success": True,
                "draft": {
                    "subject": subject,
                    "body": body,
                    "generated_at": shipment.followup_draft_generated_at.isoformat(),
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to regenerate: {str(e)}")


@app.post("/tracking/followup/approve/{tracking_id}")
async def approve_and_send_followup(tracking_id: int, user: dict = Depends(get_current_user)):
    """Approve the draft and send the followup email."""
    print(f"📬 [FOLLOWUP-APPROVE] Starting approval for tracking_id={tracking_id}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [FOLLOWUP-APPROVE] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import ShipmentTracking
    from sqlalchemy import select

    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emma_service'))
    try:
        from followup_service import send_followup_email
    except ImportError as e:
        print(f"❌ [FOLLOWUP-APPROVE] Followup service import failed: {e}")
        raise HTTPException(status_code=500, detail="Followup service not available")

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            print(f"❌ [FOLLOWUP-APPROVE] Shipment {tracking_id} not found")
            raise HTTPException(status_code=404, detail="Shipment not found")

        print(f"📬 [FOLLOWUP-APPROVE] Found shipment for {shipment.customer_email}, order #{shipment.order_number}")

        if not shipment.followup_draft_subject or not shipment.followup_draft_body:
            print(f"❌ [FOLLOWUP-APPROVE] No draft found for shipment {tracking_id}")
            raise HTTPException(status_code=400, detail="No draft to send. Generate a draft first.")

        if shipment.delivery_followup_sent:
            print(f"❌ [FOLLOWUP-APPROVE] Followup already sent for shipment {tracking_id}")
            raise HTTPException(status_code=400, detail="Followup already sent for this shipment")

        print(f"📬 [FOLLOWUP-APPROVE] Sending followup email to {shipment.customer_email}")
        # Send the stored draft
        send_result = send_followup_email(
            to_email=shipment.customer_email,
            subject=shipment.followup_draft_subject,
            body=shipment.followup_draft_body,
        )

        if send_result.get("success"):
            shipment.delivery_followup_sent = True
            shipment.followup_status = 'sent'
            await db.commit()
            print(f"✅ [FOLLOWUP-APPROVE] Followup sent successfully to {shipment.customer_email}")
            return {
                "success": True,
                "message": f"Followup email sent to {shipment.customer_email}",
                "messageId": send_result.get("messageId"),
            }
        else:
            print(f"❌ [FOLLOWUP-APPROVE] Failed to send: {send_result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "error": send_result.get("error", "Failed to send email"),
            }


@app.post("/tracking/followup/reject/{tracking_id}")
async def reject_followup(tracking_id: int, user: dict = Depends(get_current_user)):
    """Reject/skip the followup for this shipment."""
    print(f"📬 [FOLLOWUP-REJECT] Rejecting followup for tracking_id={tracking_id}, user={user.get('email', 'unknown')}")

    if not DB_SERVICE_AVAILABLE:
        print(f"❌ [FOLLOWUP-REJECT] Database not available")
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import ShipmentTracking
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(
            select(ShipmentTracking).where(ShipmentTracking.id == tracking_id)
        )
        shipment = result.scalar_one_or_none()

        if not shipment:
            print(f"❌ [FOLLOWUP-REJECT] Shipment {tracking_id} not found")
            raise HTTPException(status_code=404, detail="Shipment not found")

        print(f"📬 [FOLLOWUP-REJECT] Rejecting followup for {shipment.customer_email}, order #{shipment.order_number}")

        # Mark as rejected - won't show in pending anymore
        shipment.followup_status = 'rejected'
        shipment.delivery_followup_sent = True  # Mark as "handled" so it doesn't show up again
        await db.commit()

        print(f"✅ [FOLLOWUP-REJECT] Followup rejected for order #{shipment.order_number}")
        return {
            "success": True,
            "message": f"Followup rejected for order #{shipment.order_number}",
        }


# ==================== DEBUG ENDPOINTS ====================

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

        shop_tz = os.getenv("SHOP_TZ", "Asia/Nicosia")
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


# ==================== META ADS MARKETING ENDPOINTS ====================

def _get_marketing_token():
    """Get Meta access token for marketing operations"""
    return os.getenv("META_ACCESS_TOKEN")


def _get_ad_account_id():
    """Get Meta Ad Account ID (strips 'act_' prefix if present since API client adds it)"""
    account_id = os.getenv("META_AD_ACCOUNT_ID", "668790152408430")
    # Strip 'act_' prefix if present - the API client adds it
    if account_id.startswith("act_"):
        account_id = account_id[4:]
    return account_id


@app.get("/meta-ads/status")
async def meta_ads_quick_status(date_range: str = "today"):
    """Get quick campaign status overview"""
    try:
        from meta_decision_engine import create_engine

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
    """Run full campaign analysis with AI recommendations"""
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        report = engine.analyze_campaign(campaign_id, date_range)
        return report

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze: {str(e)}")


@app.get("/meta-ads/campaigns")
async def meta_ads_list_campaigns():
    """List all campaigns with their status"""
    try:
        from meta_decision_engine import MetaAdsClient

        access_token = _get_marketing_token()
        ad_account_id = _get_ad_account_id()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        client = MetaAdsClient(access_token, ad_account_id)
        campaigns = client.get_campaigns()
        return {"campaigns": campaigns}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch campaigns: {str(e)}")


@app.get("/meta-ads/creatives")
async def meta_ads_list_creatives():
    """List available ad creatives"""
    try:
        from meta_decision_engine import MetaAdsClient

        access_token = _get_marketing_token()
        ad_account_id = _get_ad_account_id()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        client = MetaAdsClient(access_token, ad_account_id)
        creatives = client.get_creatives()
        return {"creatives": creatives}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch creatives: {str(e)}")


@app.get("/meta-ads/audiences")
async def meta_ads_list_audiences():
    """List custom audiences"""
    try:
        from meta_decision_engine import MetaAdsClient

        access_token = _get_marketing_token()
        ad_account_id = _get_ad_account_id()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        client = MetaAdsClient(access_token, ad_account_id)
        audiences = client.get_custom_audiences()
        return {"audiences": audiences}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch audiences: {str(e)}")


@app.get("/meta-ads/targeting-presets")
async def meta_ads_get_presets():
    """Get targeting presets for Mirai Skin campaigns"""
    try:
        from meta_decision_engine import MetaAdsClient

        # Return pre-built targeting presets for Mirai Skin
        presets = [
            {
                "name": "K-Beauty Enthusiasts",
                "description": "Women 21-45 interested in Korean skincare and beauty",
                "targeting": MetaAdsClient.build_skincare_targeting_preset()
            },
            {
                "name": "Skincare Beginners",
                "description": "Women 18-35 interested in skincare routines",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=18, age_max=35, genders=[1], countries=["US"]
                )
            },
            {
                "name": "Anti-Aging Focus",
                "description": "Women 35-55 interested in anti-aging skincare",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=35, age_max=55, genders=[1], countries=["US"]
                )
            },
            {
                "name": "Broad US Women",
                "description": "All women 21-55 in the US",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=21, age_max=55, genders=[1], countries=["US"]
                )
            }
        ]
        return {"presets": presets}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch presets: {str(e)}")


# ==================== BLOG CREATOR ENDPOINTS ====================

@app.get("/blog/categories")
async def blog_get_categories():
    """Get all blog categories"""
    try:
        from blog_service import BLOG_CATEGORIES
        return {"categories": BLOG_CATEGORIES}
    except Exception as e:
        import traceback
        print(f"[BLOG] Error in /blog/categories: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get categories: {str(e)}")


@app.get("/blog/seo-keywords/{category}")
async def blog_get_seo_keywords(category: str):
    """Get SEO keywords for a category"""
    try:
        from blog_service import BlogGenerator
        keywords = BlogGenerator.get_seo_keywords(category)
        return {"keywords": keywords, "category": category}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get keywords: {str(e)}")


@app.get("/blog/drafts")
async def blog_list_drafts():
    """List all draft articles"""
    try:
        from blog_service import BlogStorage
        from dataclasses import asdict

        storage = BlogStorage()
        drafts = storage.get_all_drafts()
        return {
            "drafts": [asdict(d) for d in drafts],
            "count": len(drafts)
        }
    except Exception as e:
        import traceback
        print(f"[BLOG] Error in /blog/drafts: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list drafts: {str(e)}")


@app.get("/blog/published")
async def blog_list_published():
    """List all published articles"""
    try:
        from blog_service import BlogStorage
        from dataclasses import asdict

        storage = BlogStorage()
        published = storage.get_all_published()
        return {
            "articles": [asdict(a) for a in published],
            "count": len(published)
        }
    except Exception as e:
        import traceback
        print(f"[BLOG] Error in /blog/published: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list published: {str(e)}")


@app.get("/blog/shopify-blogs")
async def blog_get_shopify_blogs():
    """Get list of Shopify blogs"""
    try:
        from shopify_client import fetch_blogs
        blogs = fetch_blogs()
        return {"blogs": blogs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch blogs: {str(e)}")


class BlogGenerateRequest(BaseModel):
    category: str
    topic: str
    keywords: List[str]
    word_count: int = 1000


@app.post("/blog/generate")
async def blog_generate_article(req: BlogGenerateRequest):
    """Generate a new blog article draft"""
    try:
        from blog_service import create_blog_generator
        from dataclasses import asdict

        print(f"[BLOG] Generating article: category={req.category}, topic={req.topic[:50]}...")
        generator = create_blog_generator()
        draft = generator.generate_article(
            category=req.category,
            topic=req.topic,
            keywords=req.keywords,
            word_count=req.word_count
        )
        print(f"[BLOG] Article generated: {draft.title[:50]}...")

        return {
            "success": True,
            "draft_id": draft.id,
            "title": draft.title,
            "word_count": draft.word_count,
            "draft": asdict(draft)
        }
    except ValueError as e:
        print(f"[BLOG] ValueError in /blog/generate: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[BLOG] Error in /blog/generate: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate: {str(e)}")


@app.get("/blog/seo-agent/suggestions")
async def seo_agent_get_suggestions(force_refresh: bool = False, count: int = 5):
    """Get smart content suggestions from the SEO agent"""
    try:
        from blog_service import create_seo_agent

        print(f"[SEO] Getting suggestions: force_refresh={force_refresh}, count={count}")
        agent = create_seo_agent()

        if force_refresh:
            print(f"[SEO] Force refresh - generating new suggestions...")
            suggestions = agent.generate_smart_suggestions(count=count, force_refresh=True)
        else:
            suggestions = agent.get_suggestions()
            print(f"[SEO] Loaded {len(suggestions)} existing suggestions")
            if len(suggestions) < count:
                print(f"[SEO] Not enough suggestions, generating more...")
                suggestions = agent.generate_smart_suggestions(count=count)

        print(f"[SEO] Returning {len(suggestions)} suggestions")
        return {
            "suggestions": [
                {
                    "id": s.id,
                    "category": s.category,
                    "title": s.title,
                    "topic": s.topic,
                    "keywords": s.keywords,
                    "reason": s.reason,
                    "priority": s.priority,
                    "word_count": s.word_count,
                    "estimated_traffic": s.estimated_traffic,
                    "created_at": s.created_at,
                    "status": s.status
                }
                for s in suggestions
            ],
            "count": len(suggestions)
        }
    except ValueError as e:
        print(f"[SEO] ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[SEO] Error in /blog/seo-agent/suggestions: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get suggestions: {str(e)}")


@app.post("/blog/seo-agent/generate/{suggestion_id}")
async def seo_agent_generate_from_suggestion(suggestion_id: str):
    """Generate a full article draft from a suggestion"""
    try:
        from blog_service import create_seo_agent

        agent = create_seo_agent()
        draft = agent.generate_from_suggestion(suggestion_id)

        return {
            "success": True,
            "draft_id": draft.id,
            "title": draft.title,
            "word_count": draft.word_count,
            "category": draft.category
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate article: {str(e)}")


@app.post("/blog/seo-agent/dismiss/{suggestion_id}")
async def seo_agent_dismiss_suggestion(suggestion_id: str):
    """Dismiss a suggestion"""
    try:
        from blog_service import SEOAgent

        agent = SEOAgent()
        dismissed = agent.dismiss_suggestion(suggestion_id)

        if not dismissed:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        return {"success": True, "suggestion_id": suggestion_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dismiss: {str(e)}")


# ==================== SOCIAL MEDIA MANAGER ENDPOINTS ====================

class SMStrategyGenerateRequest(BaseModel):
    goals: list = []
    date_range_start: str = ""
    date_range_end: str = ""
    product_focus: list = []

class SMPostGenerateRequest(BaseModel):
    post_type: str = "photo"
    strategy_id: Optional[str] = None
    topic_hint: Optional[str] = None
    product_ids: Optional[list] = None

class SMPostUpdateRequest(BaseModel):
    caption: Optional[str] = None
    visual_direction: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    scheduled_at: Optional[str] = None
    link_url: Optional[str] = None
    product_ids: Optional[list] = None

class SMRejectRequest(BaseModel):
    reason: str = ""

class SMRegenerateRequest(BaseModel):
    hints: str

class SMConnectRequest(BaseModel):
    access_token: str
    page_id: str = ""

class SMBulkDeleteRequest(BaseModel):
    ids: List[str]


# ---------- Account Connection ----------

@app.get("/social-media/account/status")
async def sm_account_status(user: dict = Depends(require_auth)):
    """Get Instagram account connection status"""
    try:
        from social_media_service import create_social_media_storage, validate_meta_token
        storage = create_social_media_storage()
        connection = await storage.get_active_connection_async("instagram")

        if not connection:
            # Check if env vars are set as fallback (IG token or Meta token)
            env_token = os.getenv("IG_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
            env_page = os.getenv("META_PAGE_ID") or ""
            is_ig_env = env_token and env_token.startswith("IGAA")
            if env_token and (env_page or is_ig_env):
                token_info = await validate_meta_token(env_token)
                result = {
                    "connected": token_info.get("valid", False),
                    "source": "environment",
                    "token_valid": token_info.get("valid", False),
                    "token_expires_at": token_info.get("expires_at"),
                    "days_until_expiry": token_info.get("days_until_expiry"),
                    "scopes": token_info.get("scopes", []),
                    "page_id": env_page,
                    "ig_account_id": os.getenv("META_IG_ACCOUNT_ID"),
                }
                if is_ig_env:
                    result["ig_username"] = token_info.get("ig_username")
                return result
            return {"connected": False, "source": None}

        token_info = await validate_meta_token(connection["access_token"])
        connection_safe = {k: v for k, v in connection.items() if k != "access_token"}
        connection_safe["token_valid"] = token_info.get("valid", False)
        connection_safe["token_expires_at"] = token_info.get("expires_at")
        connection_safe["days_until_expiry"] = token_info.get("days_until_expiry")
        connection_safe["scopes"] = token_info.get("scopes", [])
        connection_safe["is_expired"] = token_info.get("is_expired", False)
        connection_safe["connected"] = token_info.get("valid", False)
        connection_safe["source"] = "database"
        return connection_safe
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check account status: {str(e)}")


@app.post("/social-media/account/connect")
async def sm_account_connect(req: SMConnectRequest, user: dict = Depends(require_auth)):
    """Connect an Instagram account by providing Meta access token and Page ID"""
    try:
        from social_media_service import (
            create_social_media_storage, validate_meta_token,
            exchange_for_long_lived_token, fetch_ig_account_from_token
        )

        token = req.access_token.strip()
        page_id = req.page_id.strip()
        is_ig_token = token.startswith("IGAA")

        token_info = await validate_meta_token(token)
        if not token_info.get("valid"):
            err_msg = token_info.get("error", "Invalid access token. Please check and try again.")
            raise HTTPException(status_code=400, detail=err_msg)

        token_type = "instagram" if is_ig_token else "long_lived"
        expires_at = None
        if not is_ig_token:
            if token_info.get("expires_at_ts"):
                expires_dt = datetime.utcfromtimestamp(token_info["expires_at_ts"])
                days_left = (expires_dt - datetime.utcnow()).days
                if days_left < 5:
                    exchange = await exchange_for_long_lived_token(token)
                    if exchange.get("access_token"):
                        token = exchange["access_token"]
                        token_type = "long_lived"
                        if exchange.get("expires_in"):
                            expires_at = datetime.utcnow() + timedelta(seconds=exchange["expires_in"])
                    else:
                        expires_at = expires_dt
                else:
                    expires_at = expires_dt
            elif token_info.get("days_until_expiry") is None:
                token_type = "page_token"

        ig_info = await fetch_ig_account_from_token(token, page_id)
        if ig_info.get("error"):
            raise HTTPException(status_code=400, detail=ig_info["error"])

        storage = create_social_media_storage()
        connection_data = {
            "platform": "instagram",
            "access_token": token,
            "page_id": page_id,
            "ig_account_id": ig_info.get("ig_account_id"),
            "ig_username": ig_info.get("ig_username"),
            "ig_followers": ig_info.get("ig_followers", 0),
            "ig_profile_pic": ig_info.get("ig_profile_pic"),
            "token_expires_at": expires_at,
            "token_type": token_type,
        }
        conn_id = await storage.save_connection_async(connection_data)

        return {
            "success": True,
            "connection_id": conn_id,
            "ig_username": ig_info.get("ig_username"),
            "ig_followers": ig_info.get("ig_followers", 0),
            "ig_account_id": ig_info.get("ig_account_id"),
            "ig_profile_pic": ig_info.get("ig_profile_pic"),
            "page_name": ig_info.get("page_name"),
            "token_type": token_type,
            "token_expires_at": expires_at.isoformat() if expires_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect account: {str(e)}")


@app.post("/social-media/account/refresh")
async def sm_account_refresh(user: dict = Depends(require_auth)):
    """Refresh the Instagram account token"""
    try:
        from social_media_service import (
            create_social_media_storage, refresh_long_lived_token,
            validate_meta_token, fetch_ig_account_from_token
        )
        storage = create_social_media_storage()
        connection = await storage.get_active_connection_async("instagram")
        if not connection:
            raise HTTPException(status_code=400, detail="No active Instagram connection found")

        result = await refresh_long_lived_token(connection["access_token"])
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        new_token = result["access_token"]
        expires_at = None
        if result.get("expires_in"):
            expires_at = datetime.utcnow() + timedelta(seconds=result["expires_in"])

        await storage.update_connection_async(connection["id"], {
            "access_token": new_token,
            "token_expires_at": expires_at,
            "last_validated_at": datetime.utcnow(),
        })

        ig_info = await fetch_ig_account_from_token(new_token, connection["page_id"])

        return {
            "success": True,
            "token_type": "long_lived",
            "token_expires_at": expires_at.isoformat() if expires_at else None,
            "ig_username": ig_info.get("ig_username", connection.get("ig_username")),
            "ig_followers": ig_info.get("ig_followers", connection.get("ig_followers")),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh token: {str(e)}")


@app.post("/social-media/account/disconnect")
async def sm_account_disconnect(user: dict = Depends(require_auth)):
    """Disconnect the Instagram account"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        await storage.disconnect_async("instagram")
        return {"success": True, "message": "Instagram account disconnected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect: {str(e)}")


# ---------- Profile & Voice ----------

@app.get("/social-media/profile")
async def sm_get_profile(user: dict = Depends(require_auth)):
    """Get Instagram profile + cached brand voice analysis"""
    try:
        from social_media_service import create_social_media_storage
        import json as _json
        storage = create_social_media_storage()
        cache = await storage.get_profile_cache_async()
        if cache:
            if cache.get("brand_voice_analysis"):
                try:
                    cache["brand_voice_analysis"] = _json.loads(cache["brand_voice_analysis"])
                except (_json.JSONDecodeError, TypeError):
                    pass
            return {"profile": cache}
        try:
            from social_media_service import create_instagram_publisher
            publisher = create_instagram_publisher()
            ig_id = await publisher.get_ig_account_id()
            profile = await publisher.get_profile_info(ig_id)
            return {"profile": {**profile, "ig_account_id": ig_id}}
        except Exception:
            return {"profile": None, "message": "No profile data cached. Run voice analysis first."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")


@app.post("/social-media/analyze-voice")
async def sm_analyze_voice(user: dict = Depends(require_auth)):
    """Trigger brand voice re-analysis from Instagram posts"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        result = await agent.analyze_brand_voice()
        return {"analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze voice: {str(e)}")


@app.post("/social-media/sync-products")
async def sm_sync_products(user: dict = Depends(require_auth)):
    """Sync full product catalog from Shopify into DB"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        products = await agent.sync_product_catalog()
        return {"products": products, "count": len(products)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync products: {str(e)}")


@app.post("/social-media/strategy/generate")
async def sm_generate_strategy(req: SMStrategyGenerateRequest, user: dict = Depends(require_auth)):
    """AI generates a content strategy"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        strategy = await agent.generate_strategy(
            goals=req.goals,
            date_range_start=req.date_range_start,
            date_range_end=req.date_range_end,
            product_focus=req.product_focus,
            user_email=user.get("email", "system")
        )
        return {"strategy": asdict(strategy)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate strategy: {str(e)}")


@app.get("/social-media/strategies")
async def sm_list_strategies(status: Optional[str] = None, user: dict = Depends(require_auth)):
    """List all strategies"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategies = await storage.get_all_strategies_async(status)
        return {"strategies": [asdict(s) for s in strategies]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list strategies: {str(e)}")


@app.get("/social-media/strategy/{uuid}")
async def sm_get_strategy(uuid: str, user: dict = Depends(require_auth)):
    """Get strategy detail"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get strategy: {str(e)}")


@app.post("/social-media/strategy/{uuid}/approve")
async def sm_approve_strategy(uuid: str, user: dict = Depends(require_auth)):
    """Approve a strategy"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.status = "approved"
        strategy.approved_at = datetime.utcnow().isoformat() + "Z"
        strategy.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_strategy_async(strategy)
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve strategy: {str(e)}")


@app.post("/social-media/strategy/{uuid}/reject")
async def sm_reject_strategy(uuid: str, req: SMRejectRequest, user: dict = Depends(require_auth)):
    """Reject a strategy with feedback"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.status = "rejected"
        strategy.rejection_reason = req.reason
        strategy.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_strategy_async(strategy)
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject strategy: {str(e)}")


@app.delete("/social-media/strategy/{uuid}")
async def sm_delete_strategy(uuid: str, user: dict = Depends(require_auth)):
    """Delete a strategy"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        deleted = await storage.delete_strategy_async(uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return {"deleted": True, "id": uuid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete strategy: {str(e)}")


@app.delete("/social-media/strategies/bulk")
async def sm_bulk_delete_strategies(req: SMBulkDeleteRequest, user: dict = Depends(require_auth)):
    """Bulk delete strategies"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        count = await storage.delete_strategies_bulk(req.ids)
        return {"deleted": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bulk delete strategies: {str(e)}")


@app.delete("/social-media/posts/bulk")
async def sm_bulk_delete_posts(req: SMBulkDeleteRequest, user: dict = Depends(require_auth)):
    """Bulk delete posts"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        count = await storage.delete_posts_bulk(req.ids)
        return {"deleted": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bulk delete posts: {str(e)}")


@app.get("/social-media/calendar")
async def sm_get_calendar(start_date: Optional[str] = None, end_date: Optional[str] = None,
                           user: dict = Depends(require_auth)):
    """Get posts in date range for calendar view"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        posts = await storage.get_all_posts_async(start_date=start_date, end_date=end_date)
        return {"posts": [asdict(p) for p in posts]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get calendar: {str(e)}")


@app.post("/social-media/post/generate")
async def sm_generate_post(req: SMPostGenerateRequest, user: dict = Depends(require_auth)):
    """AI generates a single post"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.generate_post_content(
            post_type=req.post_type,
            strategy_id=req.strategy_id,
            product_ids=req.product_ids,
            topic_hint=req.topic_hint,
            user_email=user.get("email", "system")
        )
        return {"post": asdict(post)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate post: {str(e)}")


@app.post("/social-media/post/generate-batch")
async def sm_generate_batch(strategy_id: str, user: dict = Depends(require_auth)):
    """AI generates multiple posts for a strategy"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        posts = await agent.generate_batch_posts(strategy_id, user_email=user.get("email", "system"))
        return {"posts": [asdict(p) for p in posts], "count": len(posts)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate batch: {str(e)}")


@app.get("/social-media/posts")
async def sm_list_posts(status: Optional[str] = None, post_type: Optional[str] = None,
                         strategy_id: Optional[str] = None, user: dict = Depends(require_auth)):
    """List posts with optional filters (excludes full media_data for performance)"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        posts = await storage.get_all_posts_async(status=status, post_type=post_type, strategy_id=strategy_id)
        result = []
        for p in posts:
            d = asdict(p)
            d.pop("media_data", None)
            # Strip full image data from carousel, keep thumbnails + count
            if d.get("media_carousel"):
                d["media_carousel"] = [
                    {"thumbnail": s.get("thumbnail", ""), "format": s.get("format", "png")}
                    for s in d["media_carousel"]
                ]
            result.append(d)
        return {"posts": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list posts: {str(e)}")


@app.get("/social-media/post/{uuid}")
async def sm_get_post(uuid: str, user: dict = Depends(require_auth)):
    """Get post detail"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get post: {str(e)}")


@app.put("/social-media/post/{uuid}")
async def sm_update_post(uuid: str, req: SMPostUpdateRequest, user: dict = Depends(require_auth)):
    """Edit post details"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if req.caption is not None:
            post.caption = req.caption
        if req.visual_direction is not None:
            post.visual_direction = req.visual_direction
        if req.media_url is not None:
            post.media_url = req.media_url
        if req.media_type is not None:
            post.media_type = req.media_type
        if req.scheduled_at is not None:
            post.scheduled_at = req.scheduled_at
        if req.link_url is not None:
            post.link_url = req.link_url
        if req.product_ids is not None:
            post.product_ids = req.product_ids
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update post: {str(e)}")


@app.post("/social-media/post/{uuid}/approve")
async def sm_approve_post(uuid: str, user: dict = Depends(require_auth)):
    """Approve post for publishing"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.status = "approved"
        post.approved_at = datetime.utcnow().isoformat() + "Z"
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve post: {str(e)}")


@app.post("/social-media/post/{uuid}/reject")
async def sm_reject_post(uuid: str, req: SMRejectRequest, user: dict = Depends(require_auth)):
    """Reject post with correction notes"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.status = "rejected"
        post.rejection_reason = req.reason
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject post: {str(e)}")


@app.delete("/social-media/post/{uuid}")
async def sm_delete_post(uuid: str, user: dict = Depends(require_auth)):
    """Delete a post"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        deleted = await storage.delete_post_async(uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"deleted": True, "id": uuid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete post: {str(e)}")


@app.post("/social-media/post/{uuid}/regenerate")
async def sm_regenerate_post(uuid: str, req: SMRegenerateRequest, user: dict = Depends(require_auth)):
    """AI regenerate post with hints"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.regenerate_post(uuid, req.hints)
        return {"post": asdict(post)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate post: {str(e)}")


@app.post("/social-media/post/{uuid}/publish")
async def sm_publish_post(uuid: str, user: dict = Depends(require_auth)):
    """Publish approved post to Instagram + Facebook"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.publish_post(uuid)
        return {"post": asdict(post)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish post: {str(e)}")


@app.post("/social-media/post/{uuid}/generate-media")
async def sm_generate_media(uuid: str, engine: str = "gemini", user: dict = Depends(require_auth)):
    """Generate AI image/video for a post. engine: gemini (default), dalle"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.generate_media_for_post(uuid, engine=engine)
        post_dict = asdict(post)
        post_dict.pop("media_data", None)  # Don't send full image back
        if post_dict.get("media_carousel"):
            post_dict["media_carousel"] = [
                {"thumbnail": s.get("thumbnail", ""), "format": s.get("format", "png")}
                for s in post_dict["media_carousel"]
            ]
        return {"post": post_dict}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate media: {str(e)}")


@app.get("/social-media/media/{uuid}")
async def sm_serve_media(uuid: str, slide: Optional[int] = None):
    """Serve generated media as raw image/video bytes (unauthenticated for Meta API).
    Use ?slide=N to serve carousel slides (0-indexed)."""
    try:
        from social_media_service import create_social_media_storage
        import base64
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post or not post.media_data:
            raise HTTPException(status_code=404, detail="Media not found")

        # Serve carousel slide if requested
        if slide is not None and slide > 0 and post.media_carousel:
            if slide < len(post.media_carousel):
                slide_data = post.media_carousel[slide]
                raw = base64.b64decode(slide_data["data"])
                fmt = slide_data.get("format", "png")
            else:
                raise HTTPException(status_code=404, detail=f"Slide {slide} not found")
        else:
            raw = base64.b64decode(post.media_data)
            fmt = post.media_data_format or "png"

        content_type = {
            "png": "image/png", "jpeg": "image/jpeg",
            "jpg": "image/jpeg", "mp4": "video/mp4",
        }.get(fmt, "application/octet-stream")
        return Response(content=raw, media_type=content_type,
                        headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to serve media: {str(e)}")


@app.delete("/social-media/post/{uuid}")
async def sm_delete_post(uuid: str, user: dict = Depends(require_auth)):
    """Delete a draft post"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        deleted = await storage.delete_post_async(uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete post: {str(e)}")


@app.get("/social-media/products")
async def sm_get_products(user: dict = Depends(require_auth)):
    """Get Shopify products for featuring in posts"""
    try:
        if DB_SERVICE_AVAILABLE and db_service:
            products = await db_service.get_products()
            return {"products": products}
        return {"products": [], "message": "Product data requires database sync"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get products: {str(e)}")


@app.get("/social-media/insights")
async def sm_get_insights(user: dict = Depends(require_auth)):
    """Overall social performance metrics"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        insights = await storage.get_insights_async()
        posts = await storage.get_all_posts_async(status="published")
        total_impressions = sum(i.impressions for i in insights)
        total_reach = sum(i.reach for i in insights)
        total_engagement = sum(i.engagement for i in insights)
        total_clicks = sum(i.website_clicks for i in insights)
        return {
            "summary": {
                "total_posts": len(posts),
                "total_impressions": total_impressions,
                "total_reach": total_reach,
                "total_engagement": total_engagement,
                "total_website_clicks": total_clicks,
                "avg_engagement_rate": round(total_engagement / total_reach * 100, 2) if total_reach else 0,
            },
            "posts": [asdict(i) for i in insights],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get insights: {str(e)}")


@app.get("/social-media/insights/post/{uuid}")
async def sm_get_post_insights(uuid: str, user: dict = Depends(require_auth)):
    """Single post performance"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        insights = await storage.get_insights_async(post_id=uuid)
        return {"insights": [asdict(i) for i in insights]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get post insights: {str(e)}")


@app.post("/social-media/insights/sync")
async def sm_sync_insights(user: dict = Depends(require_auth)):
    """Sync latest insights from Instagram API"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        synced = await agent.sync_insights()
        return {"synced": synced}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync insights: {str(e)}")


@app.get("/social-media/insights/best-times")
async def sm_best_times(user: dict = Depends(require_auth)):
    """Data-driven best posting times"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        result = await agent.suggest_optimal_times()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get best times: {str(e)}")


@app.get("/social-media/analytics")
async def sm_get_analytics(period: int = 7, end_date: Optional[str] = None,
                            user: dict = Depends(require_auth)):
    """Account analytics with period comparison, daily data, top posts, and type breakdown"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        result = await agent.get_analytics(period_days=period, end_date_str=end_date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")


@app.post("/social-media/analytics/sync")
async def sm_sync_account_analytics(days: int = 30, user: dict = Depends(require_auth)):
    """Sync account-level daily metrics from Instagram Insights API"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        post_synced = await agent.sync_insights()
        account_synced = await agent.sync_account_insights(days=days)
        return {"post_insights_synced": post_synced, "account_days_synced": account_synced}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync analytics: {str(e)}")


# ==================== AGENT SYSTEM ENDPOINTS ====================


@app.get("/agents/orchestrator/status")
async def agents_orchestrator_status(user: dict = Depends(require_auth)):
    """Get orchestrator status."""
    try:
        from agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        return orch.get_status()
    except Exception as e:
        return {"is_running": False, "error": str(e)}


@app.post("/agents/orchestrator/run")
async def agents_orchestrator_force_run(user: dict = Depends(require_auth)):
    """Force an immediate processing cycle."""
    try:
        from agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        result = await orch.force_run()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents/tasks")
async def agents_list_tasks(
    status: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_auth),
):
    """List agent tasks with optional filters."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentTask
            from sqlalchemy import select

            async with get_db() as db:
                query = select(AgentTask).order_by(AgentTask.created_at.desc()).limit(limit)
                if status:
                    query = query.where(AgentTask.status == status)
                if agent:
                    query = query.where(AgentTask.target_agent == agent)
                result = await db.execute(query)
                rows = result.scalars().all()
                return [
                    {
                        "uuid": r.uuid,
                        "source_agent": r.source_agent,
                        "target_agent": r.target_agent,
                        "task_type": r.task_type,
                        "priority": r.priority,
                        "status": r.status,
                        "error_message": r.error_message,
                        "retry_count": r.retry_count,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                        "has_result": r.result is not None,
                    }
                    for r in rows
                ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # In-memory fallback
    from agents.base_agent import BaseAgent
    tasks = getattr(BaseAgent, '_memory_tasks', [])
    filtered = tasks
    if status:
        filtered = [t for t in filtered if t.get("status") == status]
    if agent:
        filtered = [t for t in filtered if t.get("target_agent") == agent]
    return filtered[:limit]


@app.post("/agents/tasks")
async def agents_create_task(body: dict, user: dict = Depends(require_auth)):
    """Create a manual task for an agent."""
    try:
        from agents.base_agent import BaseAgent

        class _ManualAgent(BaseAgent):
            agent_name = "manual"
            def get_supported_tasks(self):
                return []

        agent = _ManualAgent()
        task_uuid = await agent.create_task(
            target_agent=body.get("target_agent", "content"),
            task_type=body.get("task_type", ""),
            params=body.get("params", {}),
            priority=body.get("priority", "normal"),
        )
        return {"uuid": task_uuid, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents/tasks/{uuid}")
async def agents_get_task(uuid: str, user: dict = Depends(require_auth)):
    """Get task details by UUID."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentTask
            from sqlalchemy import select

            async with get_db() as db:
                result = await db.execute(
                    select(AgentTask).where(AgentTask.uuid == uuid)
                )
                r = result.scalar_one_or_none()
                if not r:
                    raise HTTPException(status_code=404, detail="Task not found")
                return {
                    "uuid": r.uuid,
                    "source_agent": r.source_agent,
                    "target_agent": r.target_agent,
                    "task_type": r.task_type,
                    "priority": r.priority,
                    "params": r.params,
                    "result": r.result,
                    "depends_on": r.depends_on,
                    "parent_task_id": r.parent_task_id,
                    "status": r.status,
                    "error_message": r.error_message,
                    "retry_count": r.retry_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/agents/tasks/{uuid}/approve")
async def agents_approve_task(uuid: str, user: dict = Depends(require_auth)):
    """Approve an awaiting_approval task for execution."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentTask
            from sqlalchemy import update

            async with get_db() as db:
                await db.execute(
                    update(AgentTask)
                    .where(AgentTask.uuid == uuid)
                    .where(AgentTask.status == "awaiting_approval")
                    .values(
                        status="pending",
                        approved_by=user.get("user_id"),
                        approved_at=datetime.utcnow(),
                    )
                )
            return {"uuid": uuid, "status": "approved"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=500, detail="Database not available")


# ---- Agent Decisions ----

@app.get("/agents/decisions")
async def agents_list_decisions(
    agent: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_auth),
):
    """List recent agent decisions."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentDecision
            from sqlalchemy import select

            async with get_db() as db:
                query = select(AgentDecision).order_by(AgentDecision.created_at.desc()).limit(limit)
                if agent:
                    query = query.where(AgentDecision.agent == agent)
                result = await db.execute(query)
                rows = result.scalars().all()
                def _decision_status(r):
                    if r.rejected_at:
                        return "rejected"
                    if r.approved_at:
                        return "approved"
                    if r.requires_approval:
                        return "pending_approval"
                    return "auto_approved"

                return [
                    {
                        "uuid": r.uuid,
                        "agent": r.agent,
                        "decision_type": r.decision_type,
                        "reasoning": r.reasoning,
                        "confidence": float(r.confidence) if r.confidence else None,
                        "requires_approval": r.requires_approval,
                        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                        "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "status": _decision_status(r),
                    }
                    for r in rows
                ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    from agents.base_agent import BaseAgent
    decisions = getattr(BaseAgent, '_memory_decisions', [])
    if agent:
        decisions = [d for d in decisions if d.get("agent") == agent]
    return decisions[:limit]


@app.post("/agents/decisions/{uuid}/approve")
async def agents_approve_decision(uuid: str, user: dict = Depends(require_auth)):
    """Approve an agent decision and cascade to linked tasks."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentDecision, AgentTask
            from sqlalchemy import update

            async with get_db() as db:
                # Approve the decision
                await db.execute(
                    update(AgentDecision)
                    .where(AgentDecision.uuid == uuid)
                    .values(approved_at=datetime.utcnow(), approved_by=user.get("user_id"))
                )

                # Cascade: move all linked tasks from awaiting_approval → pending
                await db.execute(
                    update(AgentTask)
                    .where(AgentTask.decision_uuid == uuid)
                    .where(AgentTask.status == "awaiting_approval")
                    .values(
                        status="pending",
                        approved_by=user.get("user_id"),
                        approved_at=datetime.utcnow(),
                    )
                )

            return {"uuid": uuid, "status": "approved"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=500, detail="Database not available")


@app.post("/agents/decisions/{uuid}/reject")
async def agents_reject_decision(uuid: str, body: dict = {}, user: dict = Depends(require_auth)):
    """Reject an agent decision and cancel linked tasks."""
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentDecision, AgentTask
            from sqlalchemy import update

            reason = body.get("reason", "")
            async with get_db() as db:
                # Reject the decision
                await db.execute(
                    update(AgentDecision)
                    .where(AgentDecision.uuid == uuid)
                    .values(
                        rejected_at=datetime.utcnow(),
                        rejection_reason=reason,
                    )
                )

                # Cascade: cancel all linked tasks
                await db.execute(
                    update(AgentTask)
                    .where(AgentTask.decision_uuid == uuid)
                    .where(AgentTask.status == "awaiting_approval")
                    .values(
                        status="cancelled",
                        error_message=f"Decision rejected: {reason}" if reason else "Decision rejected",
                    )
                )

            return {"uuid": uuid, "status": "rejected"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=500, detail="Database not available")


# ---- Content Assets ----

@app.get("/agents/content-assets")
async def agents_list_content_assets(
    status: Optional[str] = None,
    content_pillar: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_auth),
):
    """List content assets with optional filters."""
    try:
        from agents.content_asset_store import ContentAssetStore
        from dataclasses import asdict
        store = ContentAssetStore()
        assets = await store.list_assets(status=status, content_pillar=content_pillar, limit=limit)
        return [asdict(a) for a in assets]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents/content-assets/{uuid}")
async def agents_get_content_asset(uuid: str, user: dict = Depends(require_auth)):
    """Get content asset details."""
    try:
        from agents.content_asset_store import ContentAssetStore
        from dataclasses import asdict
        store = ContentAssetStore()
        asset = await store.get_asset(uuid)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return asdict(asset)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agents/content-assets/generate")
async def agents_generate_content_asset(body: dict, user: dict = Depends(require_auth)):
    """Manually trigger content asset creation."""
    try:
        from agents.base_agent import BaseAgent

        class _ManualAgent(BaseAgent):
            agent_name = "manual"
            def get_supported_tasks(self):
                return []

        agent = _ManualAgent()
        task_uuid = await agent.create_task(
            target_agent="content",
            task_type=body.get("task_type", "create_multi_format_asset"),
            params=body.get("params", {}),
            priority="high",
        )
        return {"task_uuid": task_uuid, "status": "queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- Content Calendar ----

@app.get("/agents/calendar")
async def agents_get_calendar(
    start_date: str = "",
    end_date: str = "",
    user: dict = Depends(require_auth),
):
    """Get content calendar for a date range."""
    try:
        from agents.content_calendar import ContentCalendar
        from dataclasses import asdict
        from datetime import date as date_type

        cal = ContentCalendar()

        if not start_date:
            today = date_type.today()
            start_date = (today - timedelta(days=today.weekday())).isoformat()
        if not end_date:
            end_date = (date_type.fromisoformat(start_date) + timedelta(days=7)).isoformat()

        slots = await cal.get_week_plan(start_date)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "slots": [asdict(s) for s in slots],
            "total": len(slots),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agents/calendar/plan-week")
async def agents_plan_week(body: dict = {}, user: dict = Depends(require_auth)):
    """Trigger CMO weekly planning."""
    try:
        from agents.base_agent import BaseAgent

        class _ManualAgent(BaseAgent):
            agent_name = "manual"
            def get_supported_tasks(self):
                return []

        agent = _ManualAgent()
        task_uuid = await agent.create_task(
            target_agent="cmo",
            task_type="weekly_planning",
            params=body.get("params", {}),
            priority="high",
        )
        return {"task_uuid": task_uuid, "status": "queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- CMO Dashboard ----

@app.get("/agents/cmo/status")
async def agents_cmo_status(user: dict = Depends(require_auth)):
    """Get CMO agent status and summary."""
    try:
        from agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        orch_status = orch.get_status()

        # Count tasks by status
        task_counts = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
        if DB_SERVICE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask
                from sqlalchemy import select, func

                async with get_db() as db:
                    for status_val in task_counts:
                        result = await db.execute(
                            select(func.count()).select_from(AgentTask).where(AgentTask.status == status_val)
                        )
                        task_counts[status_val] = result.scalar() or 0
            except Exception:
                pass

        return {
            "orchestrator": orch_status,
            "task_counts": task_counts,
            "agents": ["cmo", "content", "social", "acquisition"],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/agents/cmo/kpis")
async def agents_cmo_kpis(days: int = 30, user: dict = Depends(require_auth)):
    """Get CMO KPI tracking data."""
    try:
        from agents.cmo_agent import CMOAgent
        cmo = CMOAgent()
        result = await cmo.execute_task({
            "task_type": "generate_kpi_report",
            "params": {"period_days": days}
        })
        return result.get("data", result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- Pending Count (for sidebar badge) ----

@app.get("/agents/pending-count")
async def agents_pending_count(user: dict = Depends(require_auth)):
    """Get count of pending approvals for sidebar badge."""
    counts = {"pending_decisions": 0, "pending_tasks": 0}
    if DB_SERVICE_AVAILABLE:
        try:
            from database.connection import get_db
            from database.models import AgentDecision, AgentTask
            from sqlalchemy import select, func

            async with get_db() as db:
                # Pending decisions (requires_approval=True, not yet approved or rejected)
                result = await db.execute(
                    select(func.count()).select_from(AgentDecision)
                    .where(AgentDecision.requires_approval == True)
                    .where(AgentDecision.approved_at.is_(None))
                    .where(AgentDecision.rejected_at.is_(None))
                )
                counts["pending_decisions"] = result.scalar() or 0

                # Tasks awaiting approval
                result = await db.execute(
                    select(func.count()).select_from(AgentTask)
                    .where(AgentTask.status == "awaiting_approval")
                )
                counts["pending_tasks"] = result.scalar() or 0
        except Exception:
            pass

    counts["total"] = counts["pending_decisions"] + counts["pending_tasks"]
    return counts


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("simple_server:app", host="0.0.0.0", port=port, reload=False)
