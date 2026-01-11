"""
Pricing logic - fetches directly from Shopify GraphQL API
Also fetches historical update log from Google Sheets
"""
import os
import time
import requests
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from datetime import datetime
from functools import lru_cache

load_dotenv()

# Shopify config
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

# Cache for 5 minutes
_CACHE = {}
_CACHE_TTL = 300  # seconds

# Persistent data directory - use RENDER_DISK_PATH env var if available (for Render Disk)
# Otherwise fall back to local directory
_DATA_DIR = os.getenv("RENDER_DISK_PATH", os.path.dirname(__file__))

# Log the data directory being used
print(f"📁 Data directory: {_DATA_DIR}")
print(f"   RENDER_DISK_PATH env: {os.getenv('RENDER_DISK_PATH', 'NOT SET')}")

# Ensure data directory exists
os.makedirs(_DATA_DIR, exist_ok=True)

# Persistent competitor data storage (survives cache clears AND server restarts)
_COMPETITOR_DATA_FILE = os.path.join(_DATA_DIR, "competitor_data.json")
_COMPETITOR_DATA = {}  # variant_id -> {comp_low, comp_avg, comp_high, ...}

# Persistent update log file
_UPDATE_LOG_FILE = os.path.join(_DATA_DIR, "update_log.json")
_UPDATE_LOG = []  # In-memory cache of update records

# Persistent competitor scan history
_SCAN_HISTORY_FILE = os.path.join(_DATA_DIR, "scan_history.json")
_SCAN_HISTORY = []  # List of {timestamp, variant_id, item, comp_low, comp_avg, comp_high, ...}

print(f"📁 Competitor data file: {_COMPETITOR_DATA_FILE}")
print(f"📁 Update log file: {_UPDATE_LOG_FILE}")
print(f"📁 Scan history file: {_SCAN_HISTORY_FILE}")


def _load_update_log() -> List[Dict[str, Any]]:
    """Load update log from file"""
    global _UPDATE_LOG
    try:
        if os.path.exists(_UPDATE_LOG_FILE):
            with open(_UPDATE_LOG_FILE, 'r') as f:
                import json
                _UPDATE_LOG = json.load(f)
                print(f"📂 Loaded {len(_UPDATE_LOG)} updates from {_UPDATE_LOG_FILE}")
        return _UPDATE_LOG
    except Exception as e:
        print(f"⚠️ Could not load update log: {e}")
        return []


def _save_update_log() -> None:
    """Save update log to file"""
    try:
        import json
        with open(_UPDATE_LOG_FILE, 'w') as f:
            json.dump(_UPDATE_LOG, f, indent=2)
        print(f"💾 Saved {len(_UPDATE_LOG)} updates to {_UPDATE_LOG_FILE}")
    except Exception as e:
        print(f"⚠️ Could not save update log: {e}")


def _load_competitor_data() -> Dict[str, Dict[str, Any]]:
    """Load competitor data from file"""
    global _COMPETITOR_DATA
    try:
        if os.path.exists(_COMPETITOR_DATA_FILE):
            with open(_COMPETITOR_DATA_FILE, 'r') as f:
                import json
                _COMPETITOR_DATA = json.load(f)
                print(f"📂 Loaded competitor data for {len(_COMPETITOR_DATA)} variants from {_COMPETITOR_DATA_FILE}")
        return _COMPETITOR_DATA
    except Exception as e:
        print(f"⚠️ Could not load competitor data: {e}")
        return {}


def _save_competitor_data() -> None:
    """Save competitor data to file"""
    try:
        import json
        with open(_COMPETITOR_DATA_FILE, 'w') as f:
            json.dump(_COMPETITOR_DATA, f, indent=2)
        print(f"💾 Saved competitor data for {len(_COMPETITOR_DATA)} variants to {_COMPETITOR_DATA_FILE}")
    except Exception as e:
        print(f"⚠️ Could not save competitor data: {e}")


def _load_scan_history() -> List[Dict[str, Any]]:
    """Load scan history from file"""
    global _SCAN_HISTORY
    try:
        if os.path.exists(_SCAN_HISTORY_FILE):
            with open(_SCAN_HISTORY_FILE, 'r') as f:
                import json
                _SCAN_HISTORY = json.load(f)
                print(f"📂 Loaded {len(_SCAN_HISTORY)} scan history records from {_SCAN_HISTORY_FILE}")
        return _SCAN_HISTORY
    except Exception as e:
        print(f"⚠️ Could not load scan history: {e}")
        return []


def _save_scan_history() -> None:
    """Save scan history to file"""
    try:
        import json
        with open(_SCAN_HISTORY_FILE, 'w') as f:
            json.dump(_SCAN_HISTORY, f, indent=2)
        print(f"💾 Saved {len(_SCAN_HISTORY)} scan history records to {_SCAN_HISTORY_FILE}")
    except Exception as e:
        print(f"⚠️ Could not save scan history: {e}")


# Load existing data on module import
_load_update_log()
_load_competitor_data()
_load_scan_history()

def _get_cache(key: str):
    """Get cached value if not expired"""
    if key in _CACHE:
        value, timestamp = _CACHE[key]
        if time.time() - timestamp < _CACHE_TTL:
            return value
    return None

def _set_cache(key: str, value):
    """Set cache with timestamp"""
    _CACHE[key] = (value, time.time())

def _shopify_graphql(query: str, variables: Optional[Dict] = None):
    """Execute Shopify GraphQL query"""
    if not SHOPIFY_STORE or not SHOPIFY_TOKEN:
        raise RuntimeError("Missing SHOPIFY_STORE or SHOPIFY_TOKEN environment variables")

    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": SHOPIFY_TOKEN
    }

    response = requests.post(
        url,
        json={"query": query, "variables": variables or {}},
        headers=headers,
        timeout=60
    )
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    return data


# ================== ITEMS TAB ==================
def _collect_sellable_variant_ids() -> set:
    """Get IDs of variants that are available for sale from active products"""
    sellable = set()
    cursor = None

    query = """
    query($cursor: String) {
      products(first: 150, after: $cursor, query: "status:active") {
        pageInfo { hasNextPage }
        edges {
          cursor
          node {
            id
            status
            variants(first: 100) {
              edges {
                node {
                  id
                  availableForSale
                }
              }
            }
          }
        }
      }
    }
    """

    while True:
        try:
            result = _shopify_graphql(query, {"cursor": cursor})
            products = result["data"]["products"]

            for prod_edge in products["edges"]:
                for var_edge in prod_edge["node"]["variants"]["edges"]:
                    var_node = var_edge["node"]
                    if var_node.get("availableForSale"):
                        sellable.add(var_node["id"])

            if not products["pageInfo"]["hasNextPage"]:
                break

            cursor = products["edges"][-1]["cursor"]
            time.sleep(0.05)

        except Exception as e:
            print(f"❌ Error collecting sellable variants: {e}")
            break

    print(f"ℹ️ Found {len(sellable)} sellable variants")
    return sellable


def fetch_items(market_filter: Optional[str] = None, use_cache: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch product variants from Shopify (only sellable variants from active products)
    Returns: variant_id, item, weight, cogs, retail_base, compare_at_base
    """
    # Check cache first
    cache_key = f"items_{market_filter or 'all'}"
    if use_cache:
        cached = _get_cache(cache_key)
        if cached is not None:
            print(f"✅ Using cached items data ({len(cached)} items)")
            return cached

    # First, get the list of sellable variant IDs
    sellable = _collect_sellable_variant_ids()

    items = []
    cursor = None

    # GraphQL query matching price-bot structure
    query = """
    query($cursor: String) {
      productVariants(first: 200, after: $cursor) {
        pageInfo { hasNextPage }
        edges {
          cursor
          node {
            id
            sku
            title
            price
            compareAtPrice
            product {
              title
              status
            }
            inventoryItem {
              id
              unitCost {
                amount
                currencyCode
              }
              measurement {
                weight {
                  value
                  unit
                }
              }
            }
          }
        }
      }
    }
    """

    total_admin = 0
    kept = 0

    while True:
        try:
            result = _shopify_graphql(query, {"cursor": cursor})
            variants = result["data"]["productVariants"]

            for edge in variants["edges"]:
                node = edge["node"]
                total_admin += 1

                gid = node["id"]

                # Skip if not in sellable list
                if gid not in sellable:
                    continue

                kept += 1

                # Build item name (matching price-bot format)
                product_title = node["product"]["title"]
                variant_title = node["title"]
                item_name = f"{product_title} — {variant_title}".strip(" — ")

                # Get weight in grams from measurement
                grams = 0.0
                inv_item = node.get("inventoryItem") or {}
                meas = inv_item.get("measurement")
                if meas and meas.get("weight"):
                    w = float(meas["weight"]["value"] or 0)
                    unit = (meas["weight"]["unit"] or "GRAMS").upper()
                    weight_map = {
                        "GRAMS": w,
                        "KILOGRAMS": w * 1000.0,
                        "POUNDS": w * 453.59237,
                        "OUNCES": w * 28.349523125
                    }
                    grams = weight_map.get(unit, w)

                # Get COGS
                cogs = 0.0
                uc = inv_item.get("unitCost")
                if uc:
                    cogs = float(uc["amount"] or 0)

                # Get prices
                retail_base = float(node["price"] or 0)
                compare_at = float(node["compareAtPrice"] or 0) if node["compareAtPrice"] else 0.0

                # Extract numeric variant ID from GID
                import re
                match = re.search(r'(\d+)$', gid)
                variant_id = match.group(1) if match else gid

                items.append({
                    "variant_id": str(variant_id),
                    "item": item_name,
                    "weight": round(grams, 1),
                    "cogs": round(cogs, 2),
                    "retail_base": round(retail_base, 2),
                    "compare_at_base": round(compare_at, 2),
                })

            # Check if there are more pages
            if not variants["pageInfo"]["hasNextPage"]:
                break

            cursor = variants["edges"][-1]["cursor"]
            time.sleep(0.05)  # Rate limiting

        except Exception as e:
            print(f"❌ Error fetching variants: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"ℹ️ Filtered to {kept} sellable variants from ACTIVE products out of {total_admin} admin variants total.")

    # Cache the results
    _set_cache(cache_key, items)

    return items


# ================== PRICE UPDATES TAB ==================
def fetch_price_updates() -> List[Dict[str, Any]]:
    """
    Get pending price updates
    For now, returns empty list - will be populated when user adds updates
    """
    # This will be implemented when we add update functionality
    return []


# ================== UPDATE LOG TAB ==================
def fetch_update_log(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get price update history from Google Sheets
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Google Sheets config (using _1 suffix to avoid conflict with reports)
        SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME_1", "mirai price bot")
        SHEET_ID = os.getenv("GOOGLE_SHEET_ID_1")
        GOOGLE_AUTH_MODE = os.getenv("GOOGLE_AUTH_MODE_1", "oauth").lower()

        if not SHEET_ID:
            print("⚠️ GOOGLE_SHEET_ID_1 not configured")
            return []

        # Authenticate
        if GOOGLE_AUTH_MODE == "service_account":
            SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_1")
            if not SERVICE_ACCOUNT_JSON or not os.path.exists(SERVICE_ACCOUNT_JSON):
                print("⚠️ Service account JSON not found")
                return []

            SCOPES = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
            gc = gspread.authorize(creds)
        else:  # oauth mode
            OAUTH_DIR = os.getenv("GOOGLE_OAUTH_DIR_1", ".google_oauth_1")
            token_path = os.path.join(OAUTH_DIR, "token.json")

            if not os.path.exists(token_path):
                print("⚠️ OAuth token not found. Run auth_google.py first.")
                return []

            gc = gspread.oauth(
                credentials_filename=os.path.join(OAUTH_DIR, "credentials.json"),
                authorized_user_filename=token_path
            )

        # Open sheet
        sh = gc.open_by_key(SHEET_ID)

        # Get UpdatesLog worksheet
        try:
            ws = sh.worksheet("UpdatesLog")
        except:
            print("⚠️ UpdatesLog worksheet not found")
            return []

        # Get all values
        values = ws.get_all_values()

        if not values or len(values) < 2:
            return []

        # Parse header and data
        headers = [h.strip().lower() for h in values[0]]
        data_rows = values[1:]

        # Map to expected format
        result = []
        for row in data_rows:
            if not row or not row[0]:  # Skip empty rows
                continue

            record = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    record[header] = row[i]

            # Normalize column names to match frontend expectations
            normalized = {
                "timestamp": record.get("timestamp", ""),
                "item": record.get("item", ""),
                "variant_id": record.get("variant_gid", "").split("/")[-1] if "/" in record.get("variant_gid", "") else record.get("variant_gid", ""),
                "market": record.get("scope", "").upper() if record.get("scope") else "US",
                "currency": record.get("currency", "USD"),
                "old_price": float(record.get("old_price", 0) or 0),
                "new_price": float(record.get("new_price", 0) or 0),
                "old_compare_at": float(record.get("old_compare_at", 0) or 0),
                "new_compare_at": float(record.get("new_compare_at", 0) or 0),
                "status": "success",  # Historical records are successful
                "notes": record.get("note", "")
            }

            # Calculate change percentage
            if normalized["old_price"] > 0:
                change = ((normalized["new_price"] - normalized["old_price"]) / normalized["old_price"]) * 100
                normalized["change_pct"] = round(change, 2)
            else:
                normalized["change_pct"] = 0.0

            result.append(normalized)

        # Sort by timestamp descending (most recent first)
        result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply limit if specified
        if limit and limit > 0:
            result = result[:limit]

        print(f"✅ Loaded {len(result)} update log entries from Google Sheets")
        return result

    except ImportError:
        print("⚠️ gspread not installed, using in-memory log")
        return _get_inmemory_update_log(limit)
    except Exception as e:
        print(f"⚠️ Google Sheets error, using in-memory log: {e}")
        return _get_inmemory_update_log(limit)


def _get_inmemory_update_log(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get update log from in-memory storage"""
    result = sorted(_UPDATE_LOG, key=lambda x: x.get("timestamp", ""), reverse=True)
    if limit and limit > 0:
        result = result[:limit]
    return result


def log_price_update(
    variant_id: str,
    item: str,
    old_price: float,
    new_price: float,
    old_compare_at: float = 0.0,
    new_compare_at: float = 0.0,
    status: str = "success",
    notes: str = ""
) -> None:
    """
    Log a price update to the update log

    Args:
        variant_id: The variant ID
        item: Product name
        old_price: Previous price
        new_price: New price
        old_compare_at: Previous compare at price
        new_compare_at: New compare at price
        status: Update status (success/failed)
        notes: Optional notes
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Calculate change percentage
    change_pct = 0.0
    if old_price > 0:
        change_pct = round(((new_price - old_price) / old_price) * 100, 2)

    record = {
        "timestamp": timestamp,
        "variant_id": str(variant_id),
        "item": item,
        "currency": "USD",
        "old_price": old_price,
        "new_price": new_price,
        "old_compare_at": old_compare_at,
        "new_compare_at": new_compare_at,
        "change_pct": change_pct,
        "status": status,
        "notes": notes
    }

    # Add to log
    _UPDATE_LOG.append(record)

    # Keep only last 5000 records
    if len(_UPDATE_LOG) > 5000:
        _UPDATE_LOG.pop(0)

    # Save to file for persistence
    _save_update_log()

    print(f"📝 Logged update: {variant_id} ${old_price} -> ${new_price} ({status})")


def clear_update_log() -> None:
    """Clear the update log (both memory and file)"""
    _UPDATE_LOG.clear()
    _save_update_log()


def invalidate_cache(keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Invalidate cache entries to force fresh data fetch

    Args:
        keys: Optional list of specific keys to clear.
              If None, clears all cache.

    Returns:
        Dict with cleared key count
    """
    global _CACHE

    if keys is None:
        # Clear all cache
        count = len(_CACHE)
        _CACHE.clear()
        print(f"🔄 Cleared all {count} cache entries")
        return {"cleared": count, "keys": "all"}
    else:
        # Clear specific keys
        cleared = []
        for key in keys:
            if key in _CACHE:
                del _CACHE[key]
                cleared.append(key)
        print(f"🔄 Cleared {len(cleared)} cache entries: {cleared}")
        return {"cleared": len(cleared), "keys": cleared}


# ================== TARGET PRICES TAB ==================
def fetch_target_prices(country_filter: Optional[str] = "US", use_cache: bool = True) -> List[Dict[str, Any]]:
    """
    Calculate target prices based on Shopify data
    Returns calculated metrics for each variant
    """
    # Define country at the start
    country = (country_filter or "US").upper()

    # Check cache first
    cache_key = f"target_prices_{country}"
    if use_cache:
        cached = _get_cache(cache_key)
        if cached is not None:
            print(f"✅ Using cached target prices data ({len(cached)} items)")
            return cached

    # Get base items data (will also use cache)
    items = fetch_items(use_cache=use_cache)

    target_prices = []

    # Constants for calculations (same as price-bot)
    CPA_USD = 15.0  # Target CPA
    PSP_FEE_RATE = 0.05  # 5% PSP fees
    TARGET_PROFIT_ON_COST = 0.4  # 40% profit margin target

    for item in items:
        variant_id = item["variant_id"]
        cogs = item["cogs"]
        weight_g = item["weight"]
        current_price = item["retail_base"]

        # Estimate shipping cost (simplified - can be enhanced with shipping matrix)
        # Rough estimate: $5 base + $0.01 per gram
        ship_cost = 5.0 + (weight_g * 0.01)

        # Calculate breakeven
        # Breakeven = COGS + Shipping + PSP fees + CPA
        psp_fees = current_price * PSP_FEE_RATE if current_price > 0 else 0
        breakeven = cogs + ship_cost + psp_fees + CPA_USD

        # Calculate target price
        # Target = (COGS + Shipping + CPA) * (1 + TARGET_PROFIT_ON_COST) / (1 - PSP_FEE_RATE)
        base_cost = cogs + ship_cost + CPA_USD
        target_price = base_cost * (1 + TARGET_PROFIT_ON_COST) / (1 - PSP_FEE_RATE)

        # Suggested price (same as target for now)
        suggested_price = target_price

        # Final suggested (use current if reasonable, otherwise use target)
        if current_price >= breakeven and current_price >= cogs * 2:
            final_suggested = current_price
        else:
            final_suggested = suggested_price

        # Calculate loss/profit
        if current_price > 0:
            revenue = current_price
            total_cost = cogs + ship_cost + psp_fees + CPA_USD
            loss_amount = revenue - total_cost
        else:
            loss_amount = 0

        # Calculate increase percentage
        if current_price > 0:
            inc_pct = ((final_suggested - current_price) / current_price) * 100
        else:
            inc_pct = 0

        # Priority
        if loss_amount < 0:
            priority = "HIGH"
        elif inc_pct > 20:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        # Get competitor data if available
        comp_data = _COMPETITOR_DATA.get(str(variant_id), {})
        comp_low = comp_data.get("comp_low", 0.0) or 0.0
        comp_avg = comp_data.get("comp_avg", 0.0) or 0.0
        comp_high = comp_data.get("comp_high", 0.0) or 0.0

        # Calculate competitive price if we have competitor data
        competitive_price = 0.0
        comp_note = "N/A"
        if comp_avg > 0:
            # Undercut average by 3%, but maintain minimum margin
            min_margin = 0.25  # 25% minimum margin
            min_price = cogs * (1 + min_margin) if cogs > 0 else 0
            target_competitive = comp_avg * 0.97  # 3% undercut

            if target_competitive >= min_price:
                competitive_price = target_competitive
                comp_note = "3% below avg"
            elif min_price > 0:
                competitive_price = min_price
                comp_note = "Floor (25% margin)"

            # Recalculate final_suggested with competitor data
            if competitive_price > 0 and competitive_price < final_suggested:
                final_suggested = competitive_price

        # Build result with country suffix (country already defined at function start)
        result = {
            "variant_id": variant_id,
            "item": item["item"],
            "weight_g": weight_g,
            "cogs": cogs,
            f"current_{country}": current_price,
            f"ship_{country}": round(ship_cost, 2),
            f"breakeven_{country}": round(breakeven, 2),
            f"target_{country}": round(target_price, 2),
            f"suggested_{country}": round(suggested_price, 2),
            f"comp_low_{country}": round(comp_low, 2),
            f"comp_avg_{country}": round(comp_avg, 2),
            f"comp_high_{country}": round(comp_high, 2),
            f"competitive_price_{country}": round(competitive_price, 2),
            f"comp_note_{country}": comp_note,
            f"final_suggested_{country}": round(final_suggested, 2),
            f"loss_amount_{country}": round(loss_amount, 2),
            f"priority_{country}": priority,
            f"inc_pct_{country}": round(inc_pct, 2),
        }

        target_prices.append(result)

    print(f"✅ Calculated {len(target_prices)} target prices for {country}")

    # Cache the results
    _set_cache(cache_key, target_prices)

    return target_prices


# ================== AVAILABLE MARKETS/COUNTRIES ==================
def get_available_markets() -> List[str]:
    """Get list of available markets"""
    # For now, return default markets
    # Can be enhanced to fetch from Shopify Markets settings
    return ["US", "UK", "AU", "CA", "EU"]


def get_available_countries() -> List[str]:
    """Get list of available countries for target pricing"""
    return ["US", "UK", "AU", "CA"]


# ================== COMPETITOR DATA STORAGE ==================
def update_competitor_data(variant_id: str, data: Dict[str, Any]) -> None:
    """
    Store competitor data for a variant (persisted to file)

    Args:
        variant_id: The variant ID
        data: Dict with comp_low, comp_avg, comp_high, etc.
    """
    _COMPETITOR_DATA[str(variant_id)] = data
    # Clear target prices cache to force recalculation with new competitor data
    keys_to_clear = [k for k in _CACHE.keys() if k.startswith("target_prices_")]
    for k in keys_to_clear:
        del _CACHE[k]
    # Save to file for persistence across restarts
    _save_competitor_data()


def get_competitor_data(variant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get stored competitor data for a variant

    Args:
        variant_id: The variant ID

    Returns:
        Dict with competitor data or None if not available
    """
    return _COMPETITOR_DATA.get(str(variant_id))


def get_all_competitor_data() -> Dict[str, Dict[str, Any]]:
    """
    Get all stored competitor data

    Returns:
        Dict mapping variant_id -> competitor data
    """
    return _COMPETITOR_DATA.copy()


def clear_competitor_data() -> None:
    """Clear all stored competitor data (and delete the file)"""
    _COMPETITOR_DATA.clear()
    _save_competitor_data()


# ================== COMPETITOR SCAN HISTORY ==================
def log_competitor_scan(variant_id: str, item: str, scan_result: Dict[str, Any], country: str = "US") -> None:
    """
    Log a competitor scan to history (JSON file + database)

    Args:
        variant_id: The variant ID that was scanned
        item: Product name
        scan_result: Dict with comp_low, comp_avg, comp_high, etc.
        country: Country code for the scan (default: US)
    """
    from datetime import datetime

    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "variant_id": str(variant_id),
        "item": item,
        "country": country,
        "comp_low": scan_result.get("comp_low"),
        "comp_avg": scan_result.get("comp_avg"),
        "comp_high": scan_result.get("comp_high"),
        "raw_count": scan_result.get("raw_count", 0),
        "trusted_count": scan_result.get("trusted_count", 0),
        "filtered_count": scan_result.get("filtered_count", 0),
        "competitive_price": scan_result.get("competitive_price"),
        "top_sellers": scan_result.get("top_sellers", []),
    }

    # Save to JSON file (legacy)
    _SCAN_HISTORY.append(record)

    # Keep only last 1000 records in JSON
    if len(_SCAN_HISTORY) > 1000:
        _SCAN_HISTORY.pop(0)

    _save_scan_history()

    # Also save to database (async)
    _save_scan_to_db(variant_id, country, scan_result)


def _save_scan_to_db(variant_id: str, country: str, scan_result: Dict[str, Any]) -> None:
    """Save scan result to database asynchronously"""
    try:
        from database.connection import is_db_configured
        if not is_db_configured():
            return

        import asyncio
        from database.service import db_service

        async def save():
            await db_service.save_scan_result(
                variant_id=str(variant_id),
                country=country,
                comp_low=scan_result.get("comp_low") or 0,
                comp_avg=scan_result.get("comp_avg") or 0,
                comp_high=scan_result.get("comp_high") or 0,
                raw_count=scan_result.get("raw_count", 0),
                trusted_count=scan_result.get("trusted_count", 0),
                filtered_count=scan_result.get("filtered_count", 0),
                top_sellers=scan_result.get("top_sellers", [])
            )

        # Try to run in existing event loop, or create new one
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(save())
        except RuntimeError:
            # No running loop, create a new one for this task
            asyncio.run(save())

    except Exception as e:
        print(f"⚠️ Could not save scan to database: {e}")


def get_scan_history(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get competitor scan history, sorted by timestamp descending

    Args:
        limit: Maximum number of records to return

    Returns:
        List of scan history records, newest first
    """
    result = sorted(_SCAN_HISTORY, key=lambda x: x.get("timestamp", ""), reverse=True)
    if limit and limit > 0:
        result = result[:limit]
    return result


def clear_scan_history() -> None:
    """Clear all scan history"""
    _SCAN_HISTORY.clear()
    _save_scan_history()
