"""
Sync products and variants from Shopify to database
"""
import os
import sys
import re
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from database.connection import get_db, init_db
from database.models import Product, Variant, Store
from sync_jobs.base_sync import BaseSyncJob, run_sync
from config import SHOPIFY_STORES
from shopify_client import _gql_for


def _shopify_graphql(query, variables, domain, token):
    """Wrapper to match expected signature"""
    return _gql_for(domain, token, query, variables)


PRODUCTS_QUERY = """
query($cursor: String) {
    products(first: 100, after: $cursor) {
        edges {
            node {
                id
                title
                status
                variants(first: 100) {
                    edges {
                        node {
                            id
                            title
                            sku
                            price
                            compareAtPrice
                            inventoryItem {
                                id
                                unitCost {
                                    amount
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
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""


class SyncProducts(BaseSyncJob):
    """Sync products from Shopify"""

    sync_type = "products"

    def __init__(self, store_key: Optional[str] = None):
        super().__init__()
        self.store_key = store_key

    def _extract_id(self, gid: str) -> str:
        """Extract numeric ID from Shopify GID"""
        match = re.search(r'(\d+)$', gid or "")
        return match.group(1) if match else gid

    def _convert_weight_to_grams(self, weight_data: dict) -> int:
        """Convert weight to grams"""
        if not weight_data:
            return 0

        value = float(weight_data.get("value", 0))
        unit = weight_data.get("unit", "GRAMS")

        if unit == "GRAMS":
            return int(value)
        elif unit == "KILOGRAMS":
            return int(value * 1000)
        elif unit == "POUNDS":
            return int(value * 453.592)
        elif unit == "OUNCES":
            return int(value * 28.3495)
        return int(value)

    async def run(self):
        """Run the sync"""
        await init_db()

        stores_to_sync = SHOPIFY_STORES
        if self.store_key:
            stores_to_sync = [s for s in SHOPIFY_STORES if s["key"] == self.store_key]

        for store_config in stores_to_sync:
            store_key = store_config["key"]
            domain = store_config["domain"]
            token = store_config["access_token"]

            print(f"📦 Syncing products for store: {store_key}")

            # Get or create store
            store = await self.get_or_create_store(
                store_key,
                store_config.get("label", store_key),
                domain
            )
            self.store_id = store.id

            # Fetch all products with pagination
            cursor = None
            products_synced = 0
            variants_synced = 0

            while True:
                print(f"  Fetching products from {domain}...")
                result = _shopify_graphql(
                    PRODUCTS_QUERY,
                    {"cursor": cursor},
                    domain=domain,
                    token=token
                )

                # Debug: Check for errors
                if result.get("errors"):
                    print(f"  ⚠️ GraphQL errors: {result['errors']}")

                # Debug: Print raw response structure
                if cursor is None:
                    print(f"  Raw result keys: {result.keys() if result else 'None'}")
                    if result and result.get("data"):
                        print(f"  Data keys: {result['data'].keys()}")

                products_data = result.get("data", {}).get("products", {})
                edges = products_data.get("edges", [])

                if cursor is None:  # First page
                    print(f"  Found {len(edges)} products on first page")

                async with get_db() as db:
                    for edge in edges:
                        node = edge.get("node", {})
                        product_gid = node.get("id")

                        if not product_gid:
                            continue

                        try:
                            # Check if product exists
                            prod_result = await db.execute(
                                select(Product).where(Product.shopify_gid == product_gid)
                            )
                            product = prod_result.scalar_one_or_none()

                            product_values = {
                                "shopify_gid": product_gid,
                                "store_id": store.id,
                                "title": node.get("title", ""),
                                "status": node.get("status", "").lower(),
                                "updated_at": datetime.utcnow()
                            }

                            if product:
                                for key, value in product_values.items():
                                    setattr(product, key, value)
                            else:
                                product = Product(**product_values)
                                db.add(product)
                                await db.flush()

                            products_synced += 1

                            # Sync variants
                            variant_edges = node.get("variants", {}).get("edges", [])
                            for var_edge in variant_edges:
                                var_node = var_edge.get("node", {})
                                variant_gid = var_node.get("id")

                                if not variant_gid:
                                    continue

                                inv_item = var_node.get("inventoryItem") or {}
                                measurement = inv_item.get("measurement") or {}
                                weight_data = measurement.get("weight") or {}

                                # Check if variant exists
                                var_result = await db.execute(
                                    select(Variant).where(Variant.shopify_gid == variant_gid)
                                )
                                variant = var_result.scalar_one_or_none()

                                variant_values = {
                                    "shopify_gid": variant_gid,
                                    "variant_id": self._extract_id(variant_gid),
                                    "product_id": product.id,
                                    "store_id": store.id,
                                    "sku": var_node.get("sku"),
                                    "title": var_node.get("title"),
                                    "price": float(var_node.get("price") or 0),
                                    "compare_at_price": float(var_node.get("compareAtPrice") or 0) if var_node.get("compareAtPrice") else None,
                                    "cogs": float((inv_item.get("unitCost", {}).get("amount") or 0)),
                                    "weight_g": self._convert_weight_to_grams(weight_data),
                                    "inventory_item_gid": inv_item.get("id"),
                                    "updated_at": datetime.utcnow()
                                }

                                if variant:
                                    for key, value in variant_values.items():
                                        setattr(variant, key, value)
                                else:
                                    variant = Variant(**variant_values)
                                    db.add(variant)

                                variants_synced += 1

                        except Exception as e:
                            print(f"  ⚠️ Error processing product {product_gid}: {e}")
                            continue

                    await db.commit()

                # Check pagination
                page_info = products_data.get("pageInfo", {})
                if page_info.get("hasNextPage"):
                    cursor = page_info.get("endCursor")
                else:
                    break

            self.records_synced = variants_synced
            print(f"  ✅ Synced {products_synced} products, {variants_synced} variants for {store_key}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync products from Shopify")
    parser.add_argument("--store", type=str, help="Specific store key to sync")
    args = parser.parse_args()

    sync = SyncProducts(store_key=args.store)
    run_sync(sync)
