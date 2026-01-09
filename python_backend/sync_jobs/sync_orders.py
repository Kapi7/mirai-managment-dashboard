"""
Sync orders from Shopify to database
"""
import os
import sys
import re
from datetime import datetime, timedelta
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from database.connection import get_db, init_db
from database.models import Order, OrderLineItem, Customer, Variant, Store
from sync_jobs.base_sync import BaseSyncJob, run_sync
from config import SHOPIFY_STORES
from shopify_client import fetch_orders_created_between_for_store


class SyncOrders(BaseSyncJob):
    """Sync orders from Shopify"""

    sync_type = "orders"

    def __init__(self, days_back: int = 7, store_key: Optional[str] = None):
        super().__init__()
        self.days_back = days_back
        self.store_key = store_key

    def _normalize_channel(self, order: dict) -> str:
        """Normalize order source to channel"""
        source_name = (order.get("sourceName") or "").lower()
        utm_source = ""
        utm_medium = ""
        referrer = ""

        # Extract UTM params
        customer_journey = order.get("customerJourney") or {}
        first_visit = customer_journey.get("firstVisit") or {}
        utm_params = first_visit.get("utmParameters") or {}
        utm_source = (utm_params.get("source") or "").lower()
        utm_medium = (utm_params.get("medium") or "").lower()
        referrer = (first_visit.get("referrerUrl") or "").lower()

        # Check for gclid
        landing_page = first_visit.get("landingPage") or ""
        has_gclid = "gclid=" in landing_page.lower()

        # Klaviyo
        if source_name == "klaviyo" or utm_source == "klaviyo" or utm_medium == "email":
            return "klaviyo"

        # Google Paid
        if has_gclid:
            return "google"
        if utm_source == "google" or utm_medium in ("cpc", "product_sync"):
            return "google"
        if source_name == "google":
            return "google"
        if any(x in referrer for x in ["google.", "youtube.", "gmail."]):
            return "google"

        # Meta
        if utm_source in ("facebook", "fb", "instagram", "ig", "meta"):
            return "meta"
        if any(x in referrer for x in ["facebook.com", "instagram.com", "fb.com"]):
            return "meta"

        # ChatGPT
        if utm_source in ("chatgpt.com", "openai", "chatgpt"):
            return "chatgpt"
        if "chatgpt.com" in referrer:
            return "chatgpt"

        # Direct
        if not utm_source and not utm_medium and not referrer:
            return "direct"

        return "organic"

    def _extract_variant_id(self, gid: str) -> str:
        """Extract numeric ID from Shopify GID"""
        match = re.search(r'(\d+)$', gid or "")
        return match.group(1) if match else gid

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

            print(f"📦 Syncing orders for store: {store_key}")

            # Get or create store
            store = await self.get_or_create_store(
                store_key,
                store_config.get("label", store_key),
                domain
            )
            self.store_id = store.id

            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=self.days_back)

            # Fetch orders from Shopify
            orders = fetch_orders_created_between_for_store(
                domain, token,
                start_date.isoformat() + "Z",
                end_date.isoformat() + "Z",
                exclude_cancelled=False
            )

            print(f"  Found {len(orders)} orders")

            async with get_db() as db:
                for order_data in orders:
                    try:
                        shopify_gid = order_data.get("id")
                        if not shopify_gid:
                            continue

                        # Check if order exists
                        result = await db.execute(
                            select(Order).where(Order.shopify_gid == shopify_gid)
                        )
                        existing = result.scalar_one_or_none()

                        # Parse order data (strip timezone to make naive UTC)
                        created_at_str = order_data.get("createdAt", "")
                        if created_at_str:
                            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                            created_at = created_at.replace(tzinfo=None)  # Convert to naive
                        else:
                            created_at = datetime.utcnow()

                        cancelled_at_str = order_data.get("cancelledAt")
                        if cancelled_at_str:
                            cancelled_at = datetime.fromisoformat(cancelled_at_str.replace("Z", "+00:00"))
                            cancelled_at = cancelled_at.replace(tzinfo=None)  # Convert to naive
                        else:
                            cancelled_at = None

                        # Customer
                        customer_data = order_data.get("customer") or {}
                        customer_gid = customer_data.get("id")
                        customer_id = None

                        if customer_gid:
                            result = await db.execute(
                                select(Customer).where(Customer.shopify_gid == customer_gid)
                            )
                            customer = result.scalar_one_or_none()

                            if not customer:
                                customer = Customer(
                                    shopify_gid=customer_gid,
                                    email=customer_data.get("email"),
                                    first_name=customer_data.get("firstName"),
                                    last_name=customer_data.get("lastName"),
                                    order_count=int(customer_data.get("numberOfOrders") or 0)
                                )
                                db.add(customer)
                                await db.flush()

                            customer_id = customer.id

                        # Shipping address
                        shipping = order_data.get("shippingAddress") or {}

                        # Calculate financials from line items
                        line_items = order_data.get("lineItems", {}).get("nodes", [])
                        gross = 0.0
                        cogs = 0.0

                        for node in line_items:
                            qty = int(node.get("quantity") or 0)
                            line_total = float((node.get("originalTotalSet", {}).get("shopMoney", {}).get("amount") or 0))
                            gross += line_total

                            variant = node.get("variant") or {}
                            inv_item = variant.get("inventoryItem") or {}
                            unit_cost = float((inv_item.get("unitCost", {}).get("amount") or 0))
                            cogs += unit_cost * qty

                        # Get discount and refund
                        discounts = float(order_data.get("totalDiscountsSet", {}).get("shopMoney", {}).get("amount") or 0)
                        refunds = float(order_data.get("totalRefundedSet", {}).get("shopMoney", {}).get("amount") or 0)
                        shipping_charged = float(order_data.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount") or 0)

                        net = gross - discounts - refunds

                        # UTM params
                        customer_journey = order_data.get("customerJourney") or {}
                        first_visit = customer_journey.get("firstVisit") or {}
                        utm_params = first_visit.get("utmParameters") or {}

                        order_values = {
                            "shopify_gid": shopify_gid,
                            "order_name": order_data.get("name", ""),
                            "store_id": store.id,
                            "customer_id": customer_id,
                            "created_at": created_at,
                            "cancelled_at": cancelled_at,
                            "gross": gross,
                            "discounts": discounts,
                            "refunds": refunds,
                            "net": net,
                            "cogs": cogs,
                            "shipping_charged": shipping_charged,
                            "country": shipping.get("country"),
                            "country_code": shipping.get("countryCodeV2"),
                            "total_weight_g": int(order_data.get("totalWeight") or 0),
                            "utm_source": utm_params.get("source"),
                            "utm_medium": utm_params.get("medium"),
                            "utm_campaign": utm_params.get("campaign"),
                            "referrer_url": first_visit.get("referrerUrl"),
                            "source_name": order_data.get("sourceName"),
                            "channel": self._normalize_channel(order_data),
                            "is_returning": int(customer_data.get("numberOfOrders") or 0) > 1,
                            "is_test": order_data.get("test", False)
                        }

                        if existing:
                            for key, value in order_values.items():
                                setattr(existing, key, value)
                            order = existing
                        else:
                            order = Order(**order_values)
                            db.add(order)
                            await db.flush()

                        # Sync line items
                        # Delete existing line items
                        await db.execute(
                            OrderLineItem.__table__.delete().where(
                                OrderLineItem.order_id == order.id
                            )
                        )

                        # Add new line items
                        for node in line_items:
                            variant_data = node.get("variant") or {}
                            variant_gid = variant_data.get("id")
                            variant_id_num = self._extract_variant_id(variant_gid)

                            # Try to find variant in DB
                            db_variant_id = None
                            if variant_gid:
                                result = await db.execute(
                                    select(Variant.id).where(Variant.shopify_gid == variant_gid)
                                )
                                db_variant = result.scalar_one_or_none()
                                db_variant_id = db_variant

                            inv_item = variant_data.get("inventoryItem") or {}
                            unit_cost = float((inv_item.get("unitCost", {}).get("amount") or 0))

                            line_item = OrderLineItem(
                                order_id=order.id,
                                variant_id=db_variant_id,
                                quantity=int(node.get("quantity") or 0),
                                gross=float(node.get("originalTotalSet", {}).get("shopMoney", {}).get("amount") or 0),
                                unit_cogs=unit_cost,
                                sku=node.get("sku") or variant_data.get("sku")
                            )
                            db.add(line_item)

                        self.records_synced += 1

                    except Exception as e:
                        print(f"  ⚠️ Error processing order: {e}")
                        continue

                await db.commit()

            print(f"  ✅ Synced {self.records_synced} orders for {store_key}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync orders from Shopify")
    parser.add_argument("--days", type=int, default=7, help="Days to sync back")
    parser.add_argument("--store", type=str, help="Specific store key to sync")
    args = parser.parse_args()

    sync = SyncOrders(days_back=args.days, store_key=args.store)
    run_sync(sync)
