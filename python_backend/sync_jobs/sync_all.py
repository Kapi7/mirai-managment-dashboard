#!/usr/bin/env python3
"""
Unified sync job - runs all sync tasks in sequence:
- Orders (includes PSP fees)
- Products
- Google Ads spend
- Meta Ads spend

Run every 5 minutes via cron: */5 * * * *
Command: cd python_backend && python sync_jobs/sync_all.py
"""
import os
import sys
import asyncio
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_all_syncs():
    """Run all sync jobs in sequence"""
    print("=" * 60)
    print(f"🚀 Starting unified sync at {datetime.utcnow().isoformat()}")
    print("=" * 60)

    results = {}

    # 1. Sync Orders (includes PSP fees)
    print("\n" + "=" * 40)
    print("📦 SYNC ORDERS + PSP FEES")
    print("=" * 40)
    try:
        from sync_jobs.sync_orders import SyncOrders
        sync = SyncOrders(days_back=7)
        await sync.execute()
        results["orders"] = f"✅ {sync.records_synced} records"
    except Exception as e:
        print(f"❌ Orders sync failed: {e}")
        results["orders"] = f"❌ {str(e)}"

    # 2. Sync Products
    print("\n" + "=" * 40)
    print("📦 SYNC PRODUCTS")
    print("=" * 40)
    try:
        from sync_jobs.sync_products import SyncProducts
        sync = SyncProducts()
        await sync.execute()
        results["products"] = f"✅ {sync.records_synced} records"
    except Exception as e:
        print(f"❌ Products sync failed: {e}")
        results["products"] = f"❌ {str(e)}"

    # 3. Sync Google Ads
    print("\n" + "=" * 40)
    print("📊 SYNC GOOGLE ADS")
    print("=" * 40)
    try:
        from sync_jobs.sync_google_ads import SyncGoogleAds
        sync = SyncGoogleAds(days_back=7)
        await sync.execute()
        results["google_ads"] = f"✅ {sync.records_synced} records"
    except Exception as e:
        print(f"❌ Google Ads sync failed: {e}")
        results["google_ads"] = f"❌ {str(e)}"

    # 4. Sync Meta Ads
    print("\n" + "=" * 40)
    print("📊 SYNC META ADS")
    print("=" * 40)
    try:
        from sync_jobs.sync_meta_ads import SyncMetaAds
        sync = SyncMetaAds(days_back=7)
        await sync.execute()
        results["meta_ads"] = f"✅ {sync.records_synced} records"
    except Exception as e:
        print(f"❌ Meta Ads sync failed: {e}")
        results["meta_ads"] = f"❌ {str(e)}"

    # Summary
    print("\n" + "=" * 60)
    print("📋 SYNC SUMMARY")
    print("=" * 60)
    for job, result in results.items():
        print(f"  {job}: {result}")
    print("=" * 60)
    print(f"✅ Unified sync completed at {datetime.utcnow().isoformat()}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_syncs())
