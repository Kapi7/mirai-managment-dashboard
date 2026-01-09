"""
Sync PSP (Payment Service Provider) fees from Shopify to database
"""
import os
import sys
from datetime import datetime, date, timedelta
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete
from database.connection import get_db, init_db
from database.models import DailyPspFee, Store
from sync_jobs.base_sync import BaseSyncJob, run_sync
from psp_fee import get_psp_fees_daily


class SyncPspFees(BaseSyncJob):
    """Sync PSP fees from Shopify Payments"""

    sync_type = "psp_fees"

    def __init__(self, days_back: int = 30, store_key: Optional[str] = "skin"):
        super().__init__()
        self.days_back = days_back
        self.store_key = store_key

    async def run(self):
        """Run the sync"""
        await init_db()

        # Get store
        store = await self.get_store(self.store_key)
        if not store:
            # Create store if doesn't exist
            store = await self.get_or_create_store(
                self.store_key,
                "Mirai Skin" if self.store_key == "skin" else self.store_key,
                os.getenv("SHOPIFY_STORE")
            )
        self.store_id = store.id

        print(f"💳 Syncing PSP fees for store: {self.store_key}")

        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=self.days_back)

        print(f"  Date range: {start_date} to {end_date}")

        # Fetch PSP fees from Shopify
        psp_fees = get_psp_fees_daily(start_date, end_date)

        if not psp_fees:
            print("  ⚠️ No PSP fees found")
            return

        print(f"  Found {len(psp_fees)} days with PSP fees")

        async with get_db() as db:
            for fee_date, fee_amount in psp_fees.items():
                try:
                    # Check if record exists
                    result = await db.execute(
                        select(DailyPspFee).where(
                            DailyPspFee.date == fee_date,
                            DailyPspFee.store_id == store.id
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.fee_amount = fee_amount
                        existing.created_at = datetime.utcnow()
                    else:
                        psp_record = DailyPspFee(
                            date=fee_date,
                            store_id=store.id,
                            fee_amount=fee_amount,
                            currency='USD'
                        )
                        db.add(psp_record)

                    self.records_synced += 1

                except Exception as e:
                    print(f"  ⚠️ Error processing {fee_date}: {e}")
                    continue

            await db.commit()

        print(f"  ✅ Synced {self.records_synced} PSP fee records")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync PSP fees from Shopify")
    parser.add_argument("--days", type=int, default=30, help="Days to sync back")
    parser.add_argument("--store", type=str, default="skin", help="Store key to sync")
    args = parser.parse_args()

    sync = SyncPspFees(days_back=args.days, store_key=args.store)
    run_sync(sync)
