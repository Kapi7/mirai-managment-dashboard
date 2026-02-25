"""
Content Calendar — Shared calendar for all channels.

The CMO fills it with strategic intent.
The Content Agent fills it with actual assets.
The Social Agent reads it for publishing schedule.
The Acquisition Agent reads it for ad creative rotation.
"""

import os
import json
import uuid as uuid_lib
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

DATABASE_AVAILABLE = bool(os.getenv("DATABASE_URL"))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CALENDAR_FILE = os.path.join(DATA_DIR, "content_calendar.json")


@dataclass
class CalendarSlotData:
    """In-memory representation of a calendar slot."""
    uuid: str
    date: str  # YYYY-MM-DD
    time_slot: str = ""  # "09:00"
    channel: str = ""  # instagram, facebook, tiktok, meta_ads, blog
    content_pillar: str = ""
    content_category: str = ""
    post_type: str = ""  # photo, reel, carousel, story, ad, article
    brief: str = ""
    product_id: str = ""
    asset_uuid: str = ""
    post_uuid: str = ""
    ad_id: str = ""
    blog_draft_uuid: str = ""
    status: str = "planned"  # planned, asset_ready, published, cancelled
    created_by_agent: str = ""
    created_at: str = ""
    updated_at: str = ""


class ContentCalendar:
    """CRUD operations for the shared content calendar."""

    async def create_slot(
        self,
        slot_date: str,
        time_slot: str,
        channel: str,
        content_pillar: str = "",
        content_category: str = "",
        post_type: str = "",
        brief: str = "",
        product_id: str = "",
        created_by_agent: str = "cmo",
    ) -> CalendarSlotData:
        """Create a new calendar slot."""
        slot = CalendarSlotData(
            uuid=str(uuid_lib.uuid4())[:12],
            date=slot_date,
            time_slot=time_slot,
            channel=channel,
            content_pillar=content_pillar,
            content_category=content_category,
            post_type=post_type,
            brief=brief,
            product_id=product_id,
            created_by_agent=created_by_agent,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )

        await self._save_slot(slot)
        return slot

    async def get_week_plan(self, week_start: str) -> List[CalendarSlotData]:
        """Get all calendar slots for a week (7 days from week_start)."""
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
        end = start + timedelta(days=7)
        return await self._list_slots_in_range(
            start.isoformat(), end.isoformat()
        )

    async def get_date_slots(self, slot_date: str) -> List[CalendarSlotData]:
        """Get all slots for a specific date."""
        return await self._list_slots_in_range(slot_date, slot_date)

    async def assign_asset(self, slot_uuid: str, asset_uuid: str):
        """Link a content asset to a calendar slot."""
        slot = await self.get_slot(slot_uuid)
        if slot:
            slot.asset_uuid = asset_uuid
            slot.status = "asset_ready"
            slot.updated_at = datetime.utcnow().isoformat()
            await self._save_slot(slot)

    async def mark_published(self, slot_uuid: str, post_uuid: str = "", ad_id: str = ""):
        """Mark a calendar slot as published."""
        slot = await self.get_slot(slot_uuid)
        if slot:
            slot.status = "published"
            if post_uuid:
                slot.post_uuid = post_uuid
            if ad_id:
                slot.ad_id = ad_id
            slot.updated_at = datetime.utcnow().isoformat()
            await self._save_slot(slot)

    async def cancel_slot(self, slot_uuid: str):
        """Cancel a calendar slot."""
        slot = await self.get_slot(slot_uuid)
        if slot:
            slot.status = "cancelled"
            slot.updated_at = datetime.utcnow().isoformat()
            await self._save_slot(slot)

    async def get_slot(self, uuid: str) -> Optional[CalendarSlotData]:
        """Get a single slot by UUID."""
        if DATABASE_AVAILABLE:
            try:
                return await self._get_slot_db(uuid)
            except Exception as e:
                print(f"⚠️ DB read failed: {e}")
        return self._get_slot_json(uuid)

    async def get_unassigned_slots(self, channel: Optional[str] = None) -> List[CalendarSlotData]:
        """Get slots that need content assets assigned."""
        all_slots = await self._list_all_slots()
        filtered = [
            s for s in all_slots
            if s.status == "planned" and not s.asset_uuid
        ]
        if channel:
            filtered = [s for s in filtered if s.channel == channel]
        return filtered

    async def get_ready_to_publish(self, channel: Optional[str] = None) -> List[CalendarSlotData]:
        """Get slots that have assets and are ready to publish."""
        all_slots = await self._list_all_slots()
        filtered = [
            s for s in all_slots
            if s.status == "asset_ready" and s.asset_uuid
        ]
        if channel:
            filtered = [s for s in filtered if s.channel == channel]
        return filtered

    # ---- Database operations ----

    async def _save_slot(self, slot: CalendarSlotData):
        if DATABASE_AVAILABLE:
            try:
                await self._save_slot_db(slot)
                return
            except Exception as e:
                print(f"⚠️ DB save failed: {e}")
        self._save_slot_json(slot)

    async def _save_slot_db(self, slot: CalendarSlotData):
        from database.connection import get_db
        from database.models import ContentCalendarSlot
        from sqlalchemy import select

        async with get_db() as db:
            existing = await db.execute(
                select(ContentCalendarSlot).where(ContentCalendarSlot.uuid == slot.uuid)
            )
            row = existing.scalar_one_or_none()

            if row:
                for key in ['time_slot', 'channel', 'content_pillar', 'content_category',
                            'post_type', 'brief', 'product_id', 'asset_uuid', 'post_uuid',
                            'ad_id', 'blog_draft_uuid', 'status', 'created_by_agent']:
                    setattr(row, key, getattr(slot, key, ""))
                row.updated_at = datetime.utcnow()
            else:
                row = ContentCalendarSlot(
                    uuid=slot.uuid,
                    date=datetime.strptime(slot.date, "%Y-%m-%d").date() if isinstance(slot.date, str) else slot.date,
                    time_slot=slot.time_slot,
                    channel=slot.channel,
                    content_pillar=slot.content_pillar,
                    content_category=slot.content_category,
                    post_type=slot.post_type,
                    brief=slot.brief,
                    product_id=slot.product_id,
                    asset_uuid=slot.asset_uuid,
                    post_uuid=slot.post_uuid,
                    ad_id=slot.ad_id,
                    blog_draft_uuid=slot.blog_draft_uuid,
                    status=slot.status,
                    created_by_agent=slot.created_by_agent,
                )
                db.add(row)

    async def _get_slot_db(self, uuid: str) -> Optional[CalendarSlotData]:
        from database.connection import get_db
        from database.models import ContentCalendarSlot
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(ContentCalendarSlot).where(ContentCalendarSlot.uuid == uuid)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            return self._row_to_slot(row)

    async def _list_slots_in_range(self, start: str, end: str) -> List[CalendarSlotData]:
        if DATABASE_AVAILABLE:
            try:
                return await self._list_range_db(start, end)
            except Exception as e:
                print(f"⚠️ DB range query failed: {e}")
        return self._list_range_json(start, end)

    async def _list_range_db(self, start: str, end: str) -> List[CalendarSlotData]:
        from database.connection import get_db
        from database.models import ContentCalendarSlot
        from sqlalchemy import select

        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        async with get_db() as db:
            query = (
                select(ContentCalendarSlot)
                .where(ContentCalendarSlot.date >= start_date)
                .where(ContentCalendarSlot.date <= end_date)
                .order_by(ContentCalendarSlot.date, ContentCalendarSlot.time_slot)
            )
            result = await db.execute(query)
            return [self._row_to_slot(row) for row in result.scalars().all()]

    async def _list_all_slots(self) -> List[CalendarSlotData]:
        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import ContentCalendarSlot
                from sqlalchemy import select

                async with get_db() as db:
                    query = (
                        select(ContentCalendarSlot)
                        .where(ContentCalendarSlot.status.in_(["planned", "asset_ready"]))
                        .order_by(ContentCalendarSlot.date, ContentCalendarSlot.time_slot)
                        .limit(100)
                    )
                    result = await db.execute(query)
                    return [self._row_to_slot(row) for row in result.scalars().all()]
            except Exception as e:
                print(f"⚠️ DB list failed: {e}")

        return self._list_all_json()

    def _row_to_slot(self, row) -> CalendarSlotData:
        return CalendarSlotData(
            uuid=row.uuid,
            date=row.date.isoformat() if isinstance(row.date, date) else str(row.date),
            time_slot=row.time_slot or "",
            channel=row.channel or "",
            content_pillar=row.content_pillar or "",
            content_category=row.content_category or "",
            post_type=row.post_type or "",
            brief=row.brief or "",
            product_id=row.product_id or "",
            asset_uuid=row.asset_uuid or "",
            post_uuid=row.post_uuid or "",
            ad_id=row.ad_id or "",
            blog_draft_uuid=row.blog_draft_uuid or "",
            status=row.status or "planned",
            created_by_agent=row.created_by_agent or "",
            created_at=row.created_at.isoformat() if row.created_at else "",
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )

    # ---- JSON file fallback ----

    def _load_json(self) -> list:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(CALENDAR_FILE):
            with open(CALENDAR_FILE) as f:
                return json.load(f)
        return []

    def _save_json_file(self, data: list):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CALENDAR_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _save_slot_json(self, slot: CalendarSlotData):
        items = self._load_json()
        d = asdict(slot)
        for i, item in enumerate(items):
            if item.get("uuid") == slot.uuid:
                items[i] = d
                break
        else:
            items.append(d)
        self._save_json_file(items)

    def _get_slot_json(self, uuid: str) -> Optional[CalendarSlotData]:
        items = self._load_json()
        for item in items:
            if item.get("uuid") == uuid:
                return CalendarSlotData(**{k: v for k, v in item.items()
                                          if k in CalendarSlotData.__dataclass_fields__})
        return None

    def _list_range_json(self, start: str, end: str) -> List[CalendarSlotData]:
        items = self._load_json()
        filtered = [
            CalendarSlotData(**{k: v for k, v in item.items()
                               if k in CalendarSlotData.__dataclass_fields__})
            for item in items
            if start <= item.get("date", "") <= end
        ]
        return sorted(filtered, key=lambda s: (s.date, s.time_slot))

    def _list_all_json(self) -> List[CalendarSlotData]:
        items = self._load_json()
        return [
            CalendarSlotData(**{k: v for k, v in item.items()
                               if k in CalendarSlotData.__dataclass_fields__})
            for item in items
            if item.get("status") in ("planned", "asset_ready")
        ]
