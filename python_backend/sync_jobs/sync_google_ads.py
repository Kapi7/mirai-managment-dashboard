"""
Sync Google Ads spend to database
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


class SyncGoogleAds(BaseSyncJob):
    """Sync Google Ads spend from Google Ads API"""

    sync_type = "google_ads"

    def __init__(self, days_back: int = 7, store_key: Optional[str] = None):
        super().__init__()
        self.days_back = days_back
        self.store_key = store_key or "skin"  # Default to main store

    async def run(self):
        """Run the sync"""
        await init_db()

        # Check if google-ads.yaml exists
        config_path = os.getenv("GOOGLE_ADS_CONFIG", "google-ads.yaml")
        if not os.path.exists(config_path):
            # Try alternate locations
            alt_paths = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "google-ads.yaml"),
                "/app/google-ads.yaml"
            ]
            for path in alt_paths:
                if os.path.exists(path):
                    config_path = path
                    break
            else:
                print("⚠️ google-ads.yaml not found, skipping Google Ads sync")
                return

        try:
            from google_ads_spend import daily_spend_usd_aligned
        except ImportError as e:
            print(f"⚠️ Could not import google_ads_spend: {e}")
            return

        # Get store
        store = await self.get_or_create_store(
            self.store_key,
            "Mirai Skin" if self.store_key == "skin" else self.store_key,
            ""
        )
        self.store_id = store.id

        shop_tz = os.getenv("REPORT_TZ", "UTC")
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=self.days_back)

        print(f"📊 Syncing Google Ads spend from {start_date} to {end_date}")

        current = start_date
        synced_count = 0

        async with get_db() as db:
            while current <= end_date:
                try:
                    day_iso = current.isoformat()

                    # Fetch spend from Google Ads
                    spend_usd = daily_spend_usd_aligned(day_iso, shop_tz, config_path)

                    # Check if record exists
                    result = await db.execute(
                        select(AdSpend).where(
                            AdSpend.date == current,
                            AdSpend.store_id == store.id,
                            AdSpend.platform == "google"
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.spend_usd = spend_usd
                        existing.spend_original = spend_usd
                        existing.currency = "USD"
                    else:
                        ad_spend = AdSpend(
                            date=current,
                            store_id=store.id,
                            platform="google",
                            account_id="all",
                            spend_usd=spend_usd,
                            spend_original=spend_usd,
                            currency="USD"
                        )
                        db.add(ad_spend)

                    synced_count += 1
                    print(f"  ✅ {day_iso}: ${spend_usd:.2f}")

                except Exception as e:
                    print(f"  ⚠️ Error syncing {current}: {e}")

                current += timedelta(days=1)

            await db.commit()

        self.records_synced = synced_count
        print(f"✅ Synced {synced_count} days of Google Ads spend")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync Google Ads spend")
    parser.add_argument("--days", type=int, default=7, help="Days to sync back")
    parser.add_argument("--store", type=str, default="skin", help="Store key")
    args = parser.parse_args()

    sync = SyncGoogleAds(days_back=args.days, store_key=args.store)
    run_sync(sync)
