"""
Pricing logic for dashboard - reads from Google Sheets price-bot data
Provides clean API endpoints for Items, PriceUpdates, UpdateLog, and TargetPrices tabs

PHASE 1 (Current): Google Sheets integration for compatibility with existing price-bot
PHASE 2 (Future): Direct integration with Korealy files + Shopify API
                  - No Google Sheets dependency
                  - Pricing data from Korealy exports
                  - Direct Shopify price updates via Admin API

The API interface (fetch_items, fetch_target_prices, etc.) will remain the same
Only the underlying data source will change
"""
import os
from typing import List, Dict, Any, Optional
import gspread
from dotenv import load_dotenv

load_dotenv()

# Google Sheets config
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
OAUTH_DIR = os.getenv("GOOGLE_OAUTH_DIR", ".google_oauth")

# Tab names
ITEMS_TAB = "Items"
PRICE_UPDATES_TAB = "PriceUpdates"
UPDATE_LOG_TAB = "UpdatesLog"
TARGET_PRICES_TAB = "TargetPrices"
PRICE_COMPARE_TAB = "PriceCompare"

def _gc():
    """Connect to Google Sheets using OAuth"""
    return gspread.oauth(
        credentials_filename=os.path.join(OAUTH_DIR, "client_secret.json"),
        authorized_user_filename=os.path.join(OAUTH_DIR, "token.json"),
    )

def _sheet_to_dict_list(ws) -> List[Dict[str, Any]]:
    """Convert Google Sheet to list of dicts"""
    try:
        records = ws.get_all_records()
        return records
    except Exception as e:
        print(f"Error reading sheet {ws.title}: {e}")
        return []


# ================== ITEMS TAB ==================
def fetch_items(market_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch items from Items tab
    Returns: variant_id, item, weight, cogs, retail_base, compare_at_base
    Optional market_filter: filter by market/country
    """
    try:
        gc = _gc()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(ITEMS_TAB)

        records = _sheet_to_dict_list(ws)

        # Clean up and format data
        items = []
        for rec in records:
            # Skip empty rows
            if not rec.get("variant_id"):
                continue

            item = {
                "variant_id": str(rec.get("variant_id", "")).strip(),
                "item": str(rec.get("item", "")).strip(),
                "weight": float(rec.get("weight", 0) or 0),
                "cogs": float(rec.get("cogs", 0) or 0),
                "retail_base": float(rec.get("retail_base", 0) or 0),
                "compare_at_base": float(rec.get("compare_at_base", 0) or 0),
            }

            # Add market if available
            if "market" in rec:
                item["market"] = str(rec.get("market", "")).strip()

            # Apply market filter if provided
            if market_filter:
                if item.get("market", "").upper() == market_filter.upper():
                    items.append(item)
            else:
                items.append(item)

        print(f"✅ Fetched {len(items)} items from {ITEMS_TAB}")
        return items

    except Exception as e:
        print(f"❌ Error fetching items: {e}")
        import traceback
        traceback.print_exc()
        return []


# ================== PRICE UPDATES TAB ==================
def fetch_price_updates() -> List[Dict[str, Any]]:
    """
    Fetch price updates pending execution
    Returns rows from PriceUpdates tab
    """
    try:
        gc = _gc()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(PRICE_UPDATES_TAB)

        records = _sheet_to_dict_list(ws)

        # Clean and format
        updates = []
        for rec in records:
            if not rec.get("variant_id"):
                continue

            update = {
                "variant_id": str(rec.get("variant_id", "")).strip(),
                "item": str(rec.get("item", "")).strip(),
                "market": str(rec.get("market", "")).strip(),
                "new_price": float(rec.get("new_price", 0) or 0),
                "current_price": float(rec.get("current_price", 0) or 0),
                "compare_at": float(rec.get("compare_at", 0) or 0),
                "notes": str(rec.get("notes", "")).strip(),
            }
            updates.append(update)

        print(f"✅ Fetched {len(updates)} price updates from {PRICE_UPDATES_TAB}")
        return updates

    except Exception as e:
        print(f"❌ Error fetching price updates: {e}")
        import traceback
        traceback.print_exc()
        return []


# ================== UPDATE LOG TAB ==================
def fetch_update_log(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Fetch update history from UpdatesLog tab
    Returns normalized log entries
    """
    try:
        gc = _gc()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(UPDATE_LOG_TAB)

        records = _sheet_to_dict_list(ws)

        # Normalize log entries
        logs = []
        for rec in records:
            if not rec.get("variant_id") and not rec.get("timestamp"):
                continue

            log = {
                "timestamp": str(rec.get("timestamp", "")).strip(),
                "variant_id": str(rec.get("variant_id", "")).strip(),
                "item": str(rec.get("item", "")).strip(),
                "market": str(rec.get("market", "")).strip(),
                "old_price": float(rec.get("old_price", 0) or 0),
                "new_price": float(rec.get("new_price", 0) or 0),
                "change_pct": float(rec.get("change_pct", 0) or 0),
                "status": str(rec.get("status", "")).strip(),
                "notes": str(rec.get("notes", "")).strip(),
            }
            logs.append(log)

        # Sort by timestamp descending (most recent first)
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply limit if specified
        if limit:
            logs = logs[:limit]

        print(f"✅ Fetched {len(logs)} log entries from {UPDATE_LOG_TAB}")
        return logs

    except Exception as e:
        print(f"❌ Error fetching update log: {e}")
        import traceback
        traceback.print_exc()
        return []


# ================== TARGET PRICES TAB ==================
def fetch_target_prices(country_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch target prices from TargetPrices tab
    Returns: variant_id, item, weight_g, cogs, current_US, ship_US, breakeven_US,
             target_US, suggested_US, comp_low_US, comp_avg_US, comp_high_US,
             competitive_price_US, comp_note_US, final_suggested_US,
             loss_amount_US, priority_US, inc_pct_US
    Optional country_filter: "US", "UK", "AU", "CA" etc.
    """
    try:
        gc = _gc()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(TARGET_PRICES_TAB)

        records = _sheet_to_dict_list(ws)

        # Define columns to fetch based on country filter
        base_cols = ["variant_id", "item", "weight_g", "cogs"]

        # If no country filter, default to US
        country = (country_filter or "US").upper()

        # Build column names with country suffix
        metric_cols = [
            f"current_{country}",
            f"ship_{country}",
            f"breakeven_{country}",
            f"target_{country}",
            f"suggested_{country}",
            f"comp_low_{country}",
            f"comp_avg_{country}",
            f"comp_high_{country}",
            f"competitive_price_{country}",
            f"comp_note_{country}",
            f"final_suggested_{country}",
            f"loss_amount_{country}",
            f"priority_{country}",
            f"inc_pct_{country}",
        ]

        prices = []
        for rec in records:
            if not rec.get("variant_id"):
                continue

            price = {
                "variant_id": str(rec.get("variant_id", "")).strip(),
                "item": str(rec.get("item", "")).strip(),
                "weight_g": float(rec.get("weight_g", 0) or 0),
                "cogs": float(rec.get("cogs", 0) or 0),
            }

            # Add country-specific metrics
            for col in metric_cols:
                val = rec.get(col, 0)
                # Handle text fields
                if "note" in col or "priority" in col:
                    price[col] = str(val or "").strip()
                else:
                    price[col] = float(val or 0)

            prices.append(price)

        print(f"✅ Fetched {len(prices)} target prices for {country} from {TARGET_PRICES_TAB}")
        return prices

    except Exception as e:
        print(f"❌ Error fetching target prices: {e}")
        import traceback
        traceback.print_exc()
        return []


# ================== AVAILABLE MARKETS/COUNTRIES ==================
def get_available_markets() -> List[str]:
    """Get list of available markets from Items tab"""
    try:
        gc = _gc()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(ITEMS_TAB)

        records = _sheet_to_dict_list(ws)
        markets = set()

        for rec in records:
            market = str(rec.get("market", "")).strip().upper()
            if market:
                markets.add(market)

        return sorted(list(markets))

    except Exception as e:
        print(f"❌ Error fetching markets: {e}")
        return ["US", "UK", "AU", "CA"]  # Default fallback


def get_available_countries() -> List[str]:
    """Get list of available countries for target prices"""
    # These are the countries with pricing data in TargetPrices sheet
    return ["US", "UK", "AU", "CA"]
