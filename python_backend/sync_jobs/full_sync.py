"""
Full sync - Initial data load from all sources
Run this once to populate the database with historical data
"""
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db, get_db, check_db_connection, is_db_configured
from database.models import Store, ShippingRate
from sync_jobs.sync_products import SyncProducts
from sync_jobs.sync_orders import SyncOrders


async def sync_shipping_rates():
    """Import shipping rates from CSV"""
    import csv

    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "shipping_matrix_all.csv"
    )

    if not os.path.exists(csv_path):
        print(f"⚠️ Shipping matrix not found at {csv_path}")
        return 0

    print("📦 Importing shipping rates...")

    count = 0
    async with get_db() as db:
        # Clear existing rates
        await db.execute(ShippingRate.__table__.delete())

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    geo = row.get("GEO", "").strip()
                    weight = row.get("WEIGHT", "0")
                    rate = row.get("STANDARD") or row.get("PRICE_USD") or row.get("PRICE") or "0"

                    # Parse weight (e.g., "0.5" kg)
                    weight_kg = float(weight.replace("kg", "").strip())

                    # Parse rate
                    rate_usd = float(rate.replace("$", "").replace(",", "").strip())

                    # Determine country code
                    country_code = None
                    if len(geo) == 2:
                        country_code = geo.upper()

                    shipping_rate = ShippingRate(
                        country=geo,
                        country_code=country_code,
                        weight_tier_kg=weight_kg,
                        rate_usd=rate_usd
                    )
                    db.add(shipping_rate)
                    count += 1

                except Exception as e:
                    print(f"  ⚠️ Error parsing row: {e}")
                    continue

        await db.commit()

    print(f"  ✅ Imported {count} shipping rates")
    return count


async def run_full_sync():
    """Run full sync of all data sources"""
    print("=" * 60)
    print("🚀 MIRAI DASHBOARD - FULL DATABASE SYNC")
    print("=" * 60)
    print(f"Started at: {datetime.utcnow().isoformat()}")
    print()

    # Check database configuration
    if not is_db_configured():
        print("❌ DATABASE_URL not configured!")
        print("   Set the DATABASE_URL environment variable to your PostgreSQL connection string")
        print("   Example: postgresql://user:pass@host:5432/dbname")
        return

    # Initialize database
    print("📊 Initializing database...")
    success = await init_db()
    if not success:
        print("❌ Database initialization failed!")
        return

    # Check connection
    if not await check_db_connection():
        print("❌ Cannot connect to database!")
        return

    print("✅ Database connected\n")

    # Run syncs
    try:
        # 1. Sync products first (needed for order line items)
        print("=" * 40)
        print("STEP 1: Syncing Products & Variants")
        print("=" * 40)
        products_sync = SyncProducts()
        await products_sync.execute()
        print()

        # 2. Sync orders (90 days of history)
        print("=" * 40)
        print("STEP 2: Syncing Orders (90 days)")
        print("=" * 40)
        orders_sync = SyncOrders(days_back=90)
        await orders_sync.execute()
        print()

        # 3. Import shipping rates
        print("=" * 40)
        print("STEP 3: Importing Shipping Rates")
        print("=" * 40)
        await sync_shipping_rates()
        print()

        print("=" * 60)
        print("✅ FULL SYNC COMPLETE!")
        print("=" * 60)
        print(f"Finished at: {datetime.utcnow().isoformat()}")

    except Exception as e:
        print(f"\n❌ Sync failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_full_sync())
