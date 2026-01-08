"""
Pricing Execution Module
Handles price updates, product management, and competitor price checking
"""

import os
import time
import requests
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Shopify config
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

# SerpAPI config
SERPAPI_KEY = os.getenv("SERPAPI_KEY")


def _shopify_graphql(query: str, variables: Dict = None):
    """Execute Shopify GraphQL query"""
    if not SHOPIFY_STORE or not SHOPIFY_TOKEN:
        raise RuntimeError("Missing SHOPIFY_STORE or SHOPIFY_TOKEN")

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


# Google Sheets logging removed - all updates tracked internally now


def execute_updates(updates: List[Any]) -> Dict[str, Any]:
    """
    Execute price updates to Shopify

    Args:
        updates: List of PriceUpdate objects

    Returns:
        Dict with updated_count, failed_count, message, details
    """
    updated_count = 0
    failed_count = 0
    details = []

    for update in updates:
        try:
            variant_id = update.variant_id
            new_price = float(update.new_price)
            policy = update.compare_at_policy
            item_name = update.item

            # Build variant GID
            variant_gid = f"gid://shopify/ProductVariant/{variant_id}"

            # Calculate compare_at based on policy
            if policy == "Manual" and update.new_compare_at is not None:
                new_compare_at = float(update.new_compare_at)
            elif policy == "B":
                # GMC-compliant: compare_at = price
                new_compare_at = new_price
            elif policy == "D":
                # Keep discount: maintain same percentage
                # Get current prices first
                query = """
                query($id: ID!) {
                    productVariant(id: $id) {
                        price
                        compareAtPrice
                    }
                }
                """
                result = _shopify_graphql(query, {"id": variant_gid})
                variant = result["data"]["productVariant"]

                current_price = float(variant["price"])
                current_compare_at = float(variant["compareAtPrice"]) if variant["compareAtPrice"] else 0.0

                # Calculate discount percentage
                if current_compare_at > 0 and current_price > 0:
                    discount_pct = (current_compare_at - current_price) / current_compare_at
                    new_compare_at = new_price / (1 - discount_pct)
                else:
                    new_compare_at = new_price
            else:
                new_compare_at = None

            # Update via GraphQL
            mutation = """
            mutation productVariantUpdate($input: ProductVariantInput!) {
                productVariantUpdate(input: $input) {
                    productVariant {
                        id
                        price
                        compareAtPrice
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """

            input_data = {
                "id": variant_gid,
                "price": str(new_price)
            }

            if new_compare_at is not None:
                input_data["compareAtPrice"] = str(new_compare_at)

            result = _shopify_graphql(mutation, {"input": input_data})

            user_errors = result["data"]["productVariantUpdate"]["userErrors"]
            if user_errors:
                error_msg = "; ".join([e["message"] for e in user_errors])
                raise RuntimeError(error_msg)

            # Update COGS if provided
            if update.new_cogs is not None and update.new_cogs > 0:
                # Get inventory item ID
                inv_query = """
                query($id: ID!) {
                    productVariant(id: $id) {
                        inventoryItem {
                            id
                        }
                    }
                }
                """
                inv_result = _shopify_graphql(inv_query, {"id": variant_gid})
                inv_item_id = inv_result["data"]["productVariant"]["inventoryItem"]["id"]

                # Update unit cost
                cost_mutation = """
                mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
                    inventoryItemUpdate(id: $id, input: $input) {
                        inventoryItem {
                            id
                            unitCost {
                                amount
                            }
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """
                cost_result = _shopify_graphql(cost_mutation, {
                    "id": inv_item_id,
                    "input": {"cost": str(update.new_cogs)}
                })

                cost_errors = cost_result["data"]["inventoryItemUpdate"]["userErrors"]
                if cost_errors:
                    print(f"⚠️ COGS update warning for {variant_id}: {cost_errors}")

            updated_count += 1
            details.append({
                "variant_id": variant_id,
                "status": "success",
                "message": f"Updated price to ${new_price:.2f}"
            })

            time.sleep(0.1)  # Rate limiting

        except Exception as e:
            failed_count += 1
            details.append({
                "variant_id": variant_id,
                "status": "failed",
                "message": str(e)
            })
            print(f"❌ Failed to update {variant_id}: {e}")

    message = f"Updated {updated_count} variants"
    if failed_count > 0:
        message += f", {failed_count} failed"

    return {
        "updated_count": updated_count,
        "failed_count": failed_count,
        "message": message,
        "details": details
    }


def execute_product_actions(actions: List[Any]) -> Dict[str, Any]:
    """
    Execute product add/delete actions

    Args:
        actions: List of ProductAction objects

    Returns:
        Dict with added_count, deleted_count, failed_count, message, details
    """
    added_count = 0
    deleted_count = 0
    failed_count = 0
    details = []

    for action in actions:
        try:
            if action.action == "delete":
                # Delete product variant
                variant_id = action.variant_id
                variant_gid = f"gid://shopify/ProductVariant/{variant_id}"

                mutation = """
                mutation productVariantDelete($id: ID!) {
                    productVariantDelete(id: $id) {
                        deletedProductVariantId
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """

                result = _shopify_graphql(mutation, {"id": variant_gid})
                user_errors = result["data"]["productVariantDelete"]["userErrors"]

                if user_errors:
                    error_msg = "; ".join([e["message"] for e in user_errors])
                    raise RuntimeError(error_msg)

                deleted_count += 1
                details.append({
                    "variant_id": variant_id,
                    "action": "delete",
                    "status": "success",
                    "message": "Deleted successfully"
                })

            elif action.action == "add":
                # Create new product
                # Note: This is simplified - full implementation would need more details
                mutation = """
                mutation productCreate($input: ProductInput!) {
                    productCreate(input: $input) {
                        product {
                            id
                            title
                            variants(first: 1) {
                                edges {
                                    node {
                                        id
                                    }
                                }
                            }
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """

                input_data = {
                    "title": action.title,
                    "variants": [{
                        "price": str(action.price),
                        "sku": action.sku,
                        "inventoryQuantities": {
                            "availableQuantity": action.inventory,
                            "locationId": "gid://shopify/Location/1"  # TODO: Make configurable
                        }
                    }]
                }

                result = _shopify_graphql(mutation, {"input": input_data})
                user_errors = result["data"]["productCreate"]["userErrors"]

                if user_errors:
                    error_msg = "; ".join([e["message"] for e in user_errors])
                    raise RuntimeError(error_msg)

                added_count += 1
                details.append({
                    "title": action.title,
                    "action": "add",
                    "status": "success",
                    "message": "Created successfully"
                })

            time.sleep(0.2)  # Rate limiting

        except Exception as e:
            failed_count += 1
            details.append({
                "action": action.action,
                "status": "failed",
                "message": str(e)
            })
            print(f"❌ Failed to execute action: {e}")

    message = f"Added {added_count}, deleted {deleted_count}"
    if failed_count > 0:
        message += f", {failed_count} failed"

    return {
        "added_count": added_count,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "message": message,
        "details": details
    }


def check_competitor_prices(variant_ids: List[str]) -> Dict[str, Any]:
    """
    Check competitor prices via SerpAPI with smart filtering

    Args:
        variant_ids: List of variant IDs to check

    Returns:
        Dict with scanned_count, results, message
    """
    if not SERPAPI_KEY:
        return {
            "scanned_count": 0,
            "results": [],
            "message": "SerpAPI key not configured. Set SERPAPI_KEY in environment."
        }

    from smart_pricing import analyze_competitor_prices

    results = []
    scanned_count = 0

    # Get product info from Shopify
    for variant_id in variant_ids:
        try:
            variant_gid = f"gid://shopify/ProductVariant/{variant_id}"

            # Get product details
            query = """
            query($id: ID!) {
                productVariant(id: $id) {
                    id
                    title
                    sku
                    product {
                        title
                    }
                }
            }
            """

            result = _shopify_graphql(query, {"id": variant_gid})
            variant = result["data"]["productVariant"]

            product_title = variant["product"]["title"]
            variant_title = variant["title"]
            sku = variant["sku"]

            # Build search query
            search_query = f"{product_title} {variant_title}"
            if sku:
                search_query += f" {sku}"

            # Call SerpAPI
            serp_params = {
                "engine": "google_shopping",
                "q": search_query,
                "gl": "us",
                "hl": "en",
                "num": 100,
                "api_key": SERPAPI_KEY
            }

            response = requests.get("https://serpapi.com/search.json", params=serp_params, timeout=60)
            response.raise_for_status()
            serp_data = response.json()

            # Extract prices
            competitor_prices = []

            for item in serp_data.get("shopping_results", []):
                price_str = item.get("extracted_price")
                if price_str:
                    competitor_prices.append({
                        "price": float(price_str),
                        "seller": item.get("source", ""),
                        "domain": item.get("link", "").split("/")[2] if item.get("link") else ""
                    })

            # Apply smart filtering
            analysis = analyze_competitor_prices(competitor_prices)

            results.append({
                "variant_id": variant_id,
                "product_name": f"{product_title} - {variant_title}",
                "raw_count": analysis["raw_count"],
                "trusted_count": analysis["trusted_count"],
                "filtered_count": analysis["filtered_count"],
                "comp_low": analysis["comp_low"],
                "comp_avg": analysis["comp_avg"],
                "comp_high": analysis["comp_high"]
            })

            scanned_count += 1
            time.sleep(0.6)  # Rate limiting for SerpAPI

        except Exception as e:
            print(f"❌ Failed to check prices for {variant_id}: {e}")
            results.append({
                "variant_id": variant_id,
                "error": str(e)
            })

    return {
        "scanned_count": scanned_count,
        "results": results,
        "message": f"Scanned {scanned_count} variants with smart filtering"
    }
