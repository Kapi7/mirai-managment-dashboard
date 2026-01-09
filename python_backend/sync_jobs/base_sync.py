"""
Base sync class with common functionality
"""
import asyncio
from datetime import datetime
from typing import Optional
from sqlalchemy import select, update
from database.connection import get_db
from database.models import SyncStatus, Store


class BaseSyncJob:
    """Base class for all sync jobs"""

    sync_type: str = "unknown"

    def __init__(self, store_id: Optional[int] = None):
        self.store_id = store_id
        self.records_synced = 0
        self.error_message = None

    async def get_store(self, store_key: str) -> Optional[Store]:
        """Get store by key, create if doesn't exist"""
        async with get_db() as db:
            result = await db.execute(
                select(Store).where(Store.key == store_key)
            )
            store = result.scalar_one_or_none()
            return store

    async def get_or_create_store(self, store_key: str, label: str, domain: str = None) -> Store:
        """Get or create a store"""
        async with get_db() as db:
            result = await db.execute(
                select(Store).where(Store.key == store_key)
            )
            store = result.scalar_one_or_none()

            if not store:
                store = Store(
                    key=store_key,
                    label=label,
                    shopify_domain=domain
                )
                db.add(store)
                await db.commit()
                await db.refresh(store)

            return store

    async def update_sync_status(self, status: str):
        """Update sync status in database"""
        async with get_db() as db:
            result = await db.execute(
                select(SyncStatus).where(
                    SyncStatus.sync_type == self.sync_type,
                    SyncStatus.store_id == self.store_id
                )
            )
            sync_status = result.scalar_one_or_none()

            if sync_status:
                sync_status.last_sync_at = datetime.utcnow()
                sync_status.last_sync_status = status
                sync_status.records_synced = self.records_synced
                sync_status.error_message = self.error_message
            else:
                sync_status = SyncStatus(
                    sync_type=self.sync_type,
                    store_id=self.store_id,
                    last_sync_at=datetime.utcnow(),
                    last_sync_status=status,
                    records_synced=self.records_synced,
                    error_message=self.error_message
                )
                db.add(sync_status)

            await db.commit()

    async def run(self):
        """Run the sync job - override in subclass"""
        raise NotImplementedError

    async def execute(self):
        """Execute the sync with status tracking"""
        print(f"🔄 Starting {self.sync_type} sync...")
        start_time = datetime.utcnow()

        try:
            await self.run()
            await self.update_sync_status("success")
            duration = (datetime.utcnow() - start_time).total_seconds()
            print(f"✅ {self.sync_type} sync complete: {self.records_synced} records in {duration:.1f}s")
        except Exception as e:
            self.error_message = str(e)
            await self.update_sync_status("failed")
            print(f"❌ {self.sync_type} sync failed: {e}")
            raise


def run_sync(sync_job: BaseSyncJob):
    """Helper to run sync job from command line"""
    asyncio.run(sync_job.execute())
