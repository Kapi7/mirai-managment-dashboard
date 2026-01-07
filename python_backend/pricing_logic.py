"""
Pricing logic - fetches directly from Shopify GraphQL API
No Google Sheets dependency
"""
import os
import time
import requests
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

# Shopify config
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

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
def fetch_items(market_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch product variants from Shopify
    Returns: variant_id, item, weight, cogs, retail_base, compare_at_base
    """
    items = []
    cursor = None

    # GraphQL query to fetch variants with cost, weight, and prices
    query = """
    query($cursor: String) {
      productVariants(first: 250, after: $cursor) {
        pageInfo { hasNextPage }
        edges {
          cursor
          node {
            id
            legacyResourceId
            title
            price
            compareAtPrice
            weight
            weightUnit
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
            }
          }
        }
      }
    }
    """

    while True:
        try:
            result = _shopify_graphql(query, {"cursor": cursor})
            variants = result["data"]["productVariants"]

            for edge in variants["edges"]:
                node = edge["node"]
                product = node["product"]

                # Skip inactive products
                if product["status"] != "ACTIVE":
                    continue

                # Extract numeric variant ID
                variant_id = node["legacyResourceId"]

                # Build item name
                product_title = product["title"]
                variant_title = node["title"]
                item_name = f"{product_title} - {variant_title}" if variant_title != "Default Title" else product_title

                # Get weight in grams
                weight = float(node["weight"] or 0)
                weight_unit = node["weightUnit"]
                if weight_unit == "KILOGRAMS":
                    weight = weight * 1000
                elif weight_unit == "POUNDS":
                    weight = weight * 453.592
                elif weight_unit == "OUNCES":
                    weight = weight * 28.3495

                # Get COGS
                cogs = 0.0
                if node["inventoryItem"] and node["inventoryItem"].get("unitCost"):
                    unit_cost = node["inventoryItem"]["unitCost"]
                    cogs = float(unit_cost["amount"] or 0)

                # Get prices
                retail_base = float(node["price"] or 0)
                compare_at_base = float(node["compareAtPrice"] or 0) if node["compareAtPrice"] else 0.0

                items.append({
                    "variant_id": str(variant_id),
                    "item": item_name,
                    "weight": round(weight, 1),
                    "cogs": round(cogs, 2),
                    "retail_base": round(retail_base, 2),
                    "compare_at_base": round(compare_at_base, 2),
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

    print(f"✅ Fetched {len(items)} items from Shopify")
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
    Get price update history
    For now, returns empty list - will be stored in database later
    """
    # This will be implemented with a database/log file
    return []


# ================== TARGET PRICES TAB ==================
def fetch_target_prices(country_filter: Optional[str] = "US") -> List[Dict[str, Any]]:
    """
    Calculate target prices based on Shopify data
    Returns calculated metrics for each variant
    """
    # Get base items data
    items = fetch_items()

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

        # Build result with country suffix
        country = country_filter.upper()
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
            f"comp_low_{country}": 0.0,  # Will be populated with competitor data later
            f"comp_avg_{country}": 0.0,
            f"comp_high_{country}": 0.0,
            f"competitive_price_{country}": 0.0,
            f"comp_note_{country}": "N/A",
            f"final_suggested_{country}": round(final_suggested, 2),
            f"loss_amount_{country}": round(loss_amount, 2),
            f"priority_{country}": priority,
            f"inc_pct_{country}": round(inc_pct, 2),
        }

        target_prices.append(result)

    print(f"✅ Calculated {len(target_prices)} target prices for {country}")
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
