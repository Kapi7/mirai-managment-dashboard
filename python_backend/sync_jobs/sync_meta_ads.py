"""
Sync Meta (Facebook/Instagram) Ads spend to database
"""
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from database.connection import get_db, init_db
from database.models import AdSpend, Store
from sync_jobs.base_sync import BaseSyncJob, run_sync


class SyncMetaAds(BaseSyncJob):
    """Sync Meta Ads spend from Meta Marketing API"""

    sync_type = "meta_ads"

    def __init__(self, days_back: int = 7, store_key: Optional[str] = None):
        super().__init__()
        self.days_back = days_back
        self.store_key = store_key or "skin"

    async def run(self):
        """Run the sync"""
        await init_db()

        # Check if Meta is configured
        token = os.getenv("META_ACCESS_TOKEN", "").strip()
        account_id = os.getenv("META_AD_ACCOUNT_ID", "").strip()

        if not token or not account_id:
            print("⚠️ META_ACCESS_TOKEN or META_AD_ACCOUNT_ID not set, skipping Meta Ads sync")
            return

        try:
            from meta_client import fetch_meta_insights_day
        except ImportError as e:
            print(f"⚠️ Could not import meta_client: {e}")
            return

        # Get store
        store = await self.get_or_create_store(
            self.store_key,
            "Mirai Skin" if self.store_key == "skin" else self.store_key,
            ""
        )
        self.store_id = store.id

        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=self.days_back)

        print(f"📊 Syncing Meta Ads spend from {start_date} to {end_date}")

        current = start_date
        synced_count = 0

        async with get_db() as db:
            while current <= end_date:
                try:
                    day_iso = current.isoformat()

                    # Fetch spend from Meta
                    result = fetch_meta_insights_day(day_iso, day_iso)
                    spend_usd = result.get("meta_spend", 0.0)
                    currency = result.get("currency", "USD")

                    # Check if record exists
                    existing_result = await db.execute(
                        select(AdSpend).where(
                            AdSpend.date == current,
                            AdSpend.store_id == store.id,
                            AdSpend.platform == "meta"
                        )
                    )
                    existing = existing_result.scalar_one_or_none()

                    if existing:
                        existing.spend_usd = spend_usd
                        existing.spend_original = spend_usd
                        existing.currency = currency
                    else:
                        ad_spend = AdSpend(
                            date=current,
                            store_id=store.id,
                            platform="meta",
                            account_id=account_id,
                            spend_usd=spend_usd,
                            spend_original=spend_usd,
                            currency=currency
                        )
                        db.add(ad_spend)

                    synced_count += 1
                    print(f"  ✅ {day_iso}: ${spend_usd:.2f} {currency}")

                except Exception as e:
                    print(f"  ⚠️ Error syncing {current}: {e}")

                current += timedelta(days=1)

            await db.commit()

        self.records_synced = synced_count
        print(f"✅ Synced {synced_count} days of Meta Ads spend")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync Meta Ads spend")
    parser.add_argument("--days", type=int, default=7, help="Days to sync back")
    parser.add_argument("--store", type=str, default="skin", help="Store key")
    args = parser.parse_args()

    sync = SyncMetaAds(days_back=args.days, store_key=args.store)
    run_sync(sync)
