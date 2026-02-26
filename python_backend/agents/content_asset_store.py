"""
Content Asset Store — CRUD operations for shared content assets.

Content assets are the bridge between organic and paid channels.
One asset can be used across Instagram, TikTok, Meta Ads, and blog.
"""

import os
import json
import uuid as uuid_lib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

DATABASE_AVAILABLE = bool(os.getenv("DATABASE_URL"))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ASSETS_FILE = os.path.join(DATA_DIR, "content_assets.json")


@dataclass
class ContentAssetData:
    """In-memory representation of a content asset."""
    uuid: str
    title: str
    content_pillar: str = ""
    content_category: str = ""
    product_ids: list = field(default_factory=list)
    brand: str = ""

    # Text variants
    headline: str = ""
    body_copy: str = ""
    cta_text: str = ""
    hashtags: list = field(default_factory=list)
    seo_keywords: list = field(default_factory=list)

    # Channel-specific text
    instagram_caption: str = ""
    tiktok_caption: str = ""
    ad_headline: str = ""
    ad_primary_text: str = ""
    blog_intro: str = ""

    # Visual content
    primary_image_data: Optional[str] = None
    primary_image_url: Optional[str] = None
    primary_image_thumbnail: Optional[str] = None
    primary_image_format: str = "png"
    carousel_images: list = field(default_factory=list)
    video_data: Optional[str] = None
    video_url: Optional[str] = None
    video_thumbnail: Optional[str] = None
    video_format: str = "mp4"
    video_duration_seconds: int = 0

    # Generation metadata
    visual_direction: str = ""
    video_direction: str = ""
    ai_model_image: str = ""
    ai_model_video: str = ""
    ai_model_text: str = ""
    generation_params: dict = field(default_factory=dict)

    # Content intent
    content_intent: str = ""  # "organic" or "acquisition"

    # Usage tracking
    used_in_organic: bool = False
    used_in_paid: bool = False
    used_in_blog: bool = False
    organic_post_ids: list = field(default_factory=list)
    ad_creative_ids: list = field(default_factory=list)
    blog_draft_ids: list = field(default_factory=list)

    # Performance
    total_impressions: int = 0
    total_engagement: int = 0
    total_clicks: int = 0
    organic_engagement_rate: float = 0.0
    ad_ctr: float = 0.0
    ad_roas: float = 0.0

    # Status
    status: str = "draft"
    created_by_agent: str = ""
    created_at: str = ""
    updated_at: str = ""


class ContentAssetStore:
    """CRUD operations for content assets. DB primary, JSON fallback."""

    async def save_asset(self, asset: ContentAssetData) -> str:
        """Save a content asset. Returns UUID."""
        if not asset.uuid:
            asset.uuid = str(uuid_lib.uuid4())[:12]
        if not asset.created_at:
            asset.created_at = datetime.utcnow().isoformat()
        asset.updated_at = datetime.utcnow().isoformat()

        if DATABASE_AVAILABLE:
            try:
                return await self._save_db(asset)
            except Exception as e:
                import traceback
                print(f"❌ DB save failed, falling back to JSON: {e}\n{traceback.format_exc()}")

        return self._save_json(asset)

    async def get_asset(self, uuid: str) -> Optional[ContentAssetData]:
        """Get a content asset by UUID."""
        if DATABASE_AVAILABLE:
            try:
                return await self._get_db(uuid)
            except Exception as e:
                import traceback
                print(f"❌ DB read failed: {e}\n{traceback.format_exc()}")
        return self._get_json(uuid)

    async def list_assets(
        self,
        status: Optional[str] = None,
        content_pillar: Optional[str] = None,
        used_in_organic: Optional[bool] = None,
        used_in_paid: Optional[bool] = None,
        limit: int = 50,
    ) -> List[ContentAssetData]:
        """List content assets with optional filters."""
        if DATABASE_AVAILABLE:
            try:
                return await self._list_db(status, content_pillar, used_in_organic, used_in_paid, limit)
            except Exception as e:
                import traceback
                print(f"❌ DB list failed: {e}\n{traceback.format_exc()}")
        return self._list_json(status, content_pillar, limit)

    async def mark_used(self, uuid: str, channel: str, reference_id: str):
        """Mark an asset as used in a specific channel."""
        asset = await self.get_asset(uuid)
        if not asset:
            return

        if channel == "organic":
            asset.used_in_organic = True
            if reference_id not in asset.organic_post_ids:
                asset.organic_post_ids.append(reference_id)
        elif channel == "paid":
            asset.used_in_paid = True
            if reference_id not in asset.ad_creative_ids:
                asset.ad_creative_ids.append(reference_id)
        elif channel == "blog":
            asset.used_in_blog = True
            if reference_id not in asset.blog_draft_ids:
                asset.blog_draft_ids.append(reference_id)

        await self.save_asset(asset)

    async def update_performance(self, uuid: str, metrics: dict):
        """Update aggregated performance metrics for an asset."""
        asset = await self.get_asset(uuid)
        if not asset:
            return

        asset.total_impressions = metrics.get("total_impressions", asset.total_impressions)
        asset.total_engagement = metrics.get("total_engagement", asset.total_engagement)
        asset.total_clicks = metrics.get("total_clicks", asset.total_clicks)
        asset.organic_engagement_rate = metrics.get("organic_engagement_rate", asset.organic_engagement_rate)
        asset.ad_ctr = metrics.get("ad_ctr", asset.ad_ctr)
        asset.ad_roas = metrics.get("ad_roas", asset.ad_roas)

        await self.save_asset(asset)

    async def delete_asset(self, uuid: str) -> bool:
        """Delete a content asset."""
        if DATABASE_AVAILABLE:
            try:
                return await self._delete_db(uuid)
            except Exception as e:
                import traceback
                print(f"❌ DB delete failed: {e}\n{traceback.format_exc()}")
        return self._delete_json(uuid)

    # ---- Database operations ----

    async def _save_db(self, asset: ContentAssetData) -> str:
        from database.connection import get_db
        from database.models import ContentAsset
        from sqlalchemy import select

        async with get_db() as db:
            existing = await db.execute(
                select(ContentAsset).where(ContentAsset.uuid == asset.uuid)
            )
            row = existing.scalar_one_or_none()

            data = asdict(asset)
            # Remove fields not in model or that need conversion
            data.pop("created_at", None)
            data.pop("updated_at", None)

            if row:
                for key, value in data.items():
                    if hasattr(row, key):
                        setattr(row, key, value)
                row.updated_at = datetime.utcnow()
            else:
                row = ContentAsset(**{k: v for k, v in data.items() if hasattr(ContentAsset, k)})
                db.add(row)

        return asset.uuid

    async def _get_db(self, uuid: str) -> Optional[ContentAssetData]:
        from database.connection import get_db
        from database.models import ContentAsset
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(ContentAsset).where(ContentAsset.uuid == uuid)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            return ContentAssetData(
                uuid=row.uuid,
                title=row.title or "",
                content_pillar=row.content_pillar or "",
                content_category=row.content_category or "",
                product_ids=row.product_ids or [],
                brand=row.brand or "",
                headline=row.headline or "",
                body_copy=row.body_copy or "",
                cta_text=row.cta_text or "",
                hashtags=row.hashtags or [],
                seo_keywords=row.seo_keywords or [],
                instagram_caption=row.instagram_caption or "",
                tiktok_caption=row.tiktok_caption or "",
                ad_headline=row.ad_headline or "",
                ad_primary_text=row.ad_primary_text or "",
                blog_intro=row.blog_intro or "",
                primary_image_data=row.primary_image_data,
                primary_image_url=row.primary_image_url,
                primary_image_thumbnail=row.primary_image_thumbnail,
                primary_image_format=row.primary_image_format or "png",
                carousel_images=row.carousel_images or [],
                video_data=row.video_data,
                video_url=row.video_url,
                video_thumbnail=row.video_thumbnail,
                video_format=row.video_format or "mp4",
                video_duration_seconds=row.video_duration_seconds or 0,
                visual_direction=row.visual_direction or "",
                video_direction=row.video_direction or "",
                ai_model_image=row.ai_model_image or "",
                ai_model_video=row.ai_model_video or "",
                ai_model_text=row.ai_model_text or "",
                generation_params=row.generation_params or {},
                used_in_organic=row.used_in_organic or False,
                used_in_paid=row.used_in_paid or False,
                used_in_blog=row.used_in_blog or False,
                organic_post_ids=row.organic_post_ids or [],
                ad_creative_ids=row.ad_creative_ids or [],
                blog_draft_ids=row.blog_draft_ids or [],
                total_impressions=row.total_impressions or 0,
                total_engagement=row.total_engagement or 0,
                total_clicks=row.total_clicks or 0,
                organic_engagement_rate=float(row.organic_engagement_rate or 0),
                ad_ctr=float(row.ad_ctr or 0),
                ad_roas=float(row.ad_roas or 0),
                status=row.status or "draft",
                created_by_agent=row.created_by_agent or "",
                created_at=row.created_at.isoformat() if row.created_at else "",
                updated_at=row.updated_at.isoformat() if row.updated_at else "",
            )

    async def _list_db(self, status, content_pillar, used_in_organic, used_in_paid, limit) -> List[ContentAssetData]:
        from database.connection import get_db
        from database.models import ContentAsset
        from sqlalchemy import select

        # Select only columns needed for list view — avoids loading
        # multi-MB blob columns (primary_image_data, video_data, etc.)
        list_columns = [
            ContentAsset.uuid, ContentAsset.title, ContentAsset.content_pillar,
            ContentAsset.content_category, ContentAsset.product_ids, ContentAsset.brand,
            ContentAsset.headline, ContentAsset.body_copy, ContentAsset.cta_text,
            ContentAsset.hashtags, ContentAsset.primary_image_thumbnail,
            ContentAsset.video_thumbnail, ContentAsset.content_intent,
            ContentAsset.used_in_organic, ContentAsset.used_in_paid,
            ContentAsset.used_in_blog, ContentAsset.total_impressions,
            ContentAsset.total_engagement, ContentAsset.total_clicks,
            ContentAsset.status, ContentAsset.created_by_agent,
            ContentAsset.created_at, ContentAsset.updated_at,
        ]

        async with get_db() as db:
            query = select(*list_columns).order_by(ContentAsset.created_at.desc()).limit(limit)
            if status:
                query = query.where(ContentAsset.status == status)
            if content_pillar:
                query = query.where(ContentAsset.content_pillar == content_pillar)
            if used_in_organic is not None:
                query = query.where(ContentAsset.used_in_organic == used_in_organic)
            if used_in_paid is not None:
                query = query.where(ContentAsset.used_in_paid == used_in_paid)

            result = await db.execute(query)
            rows = result.all()  # Returns Row tuples (not ORM objects)

            assets = []
            for row in rows:
                assets.append(ContentAssetData(
                    uuid=row.uuid,
                    title=row.title or "",
                    content_pillar=row.content_pillar or "",
                    content_category=row.content_category or "",
                    product_ids=row.product_ids or [],
                    brand=row.brand or "",
                    headline=row.headline or "",
                    body_copy=row.body_copy or "",
                    cta_text=row.cta_text or "",
                    hashtags=row.hashtags or [],
                    content_intent=row.content_intent or "",
                    primary_image_thumbnail=row.primary_image_thumbnail,
                    video_thumbnail=row.video_thumbnail,
                    used_in_organic=row.used_in_organic or False,
                    used_in_paid=row.used_in_paid or False,
                    used_in_blog=row.used_in_blog or False,
                    total_impressions=row.total_impressions or 0,
                    total_engagement=row.total_engagement or 0,
                    total_clicks=row.total_clicks or 0,
                    status=row.status or "draft",
                    created_by_agent=row.created_by_agent or "",
                    created_at=row.created_at.isoformat() if row.created_at else "",
                    updated_at=row.updated_at.isoformat() if row.updated_at else "",
                ))
            return assets

    async def _delete_db(self, uuid: str) -> bool:
        from database.connection import get_db
        from database.models import ContentAsset
        from sqlalchemy import delete as sql_delete

        async with get_db() as db:
            result = await db.execute(
                sql_delete(ContentAsset).where(ContentAsset.uuid == uuid)
            )
            return result.rowcount > 0

    # ---- JSON file fallback ----

    def _load_json(self) -> list:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(ASSETS_FILE):
            with open(ASSETS_FILE) as f:
                return json.load(f)
        return []

    def _save_json_file(self, data: list):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ASSETS_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _save_json(self, asset: ContentAssetData) -> str:
        items = self._load_json()
        d = asdict(asset)
        # Update or insert
        for i, item in enumerate(items):
            if item.get("uuid") == asset.uuid:
                items[i] = d
                break
        else:
            items.append(d)
        self._save_json_file(items)
        return asset.uuid

    def _get_json(self, uuid: str) -> Optional[ContentAssetData]:
        items = self._load_json()
        for item in items:
            if item.get("uuid") == uuid:
                return ContentAssetData(**{k: v for k, v in item.items()
                                          if k in ContentAssetData.__dataclass_fields__})
        return None

    def _list_json(self, status, content_pillar, limit) -> List[ContentAssetData]:
        items = self._load_json()
        filtered = []
        for item in items:
            if status and item.get("status") != status:
                continue
            if content_pillar and item.get("content_pillar") != content_pillar:
                continue
            filtered.append(ContentAssetData(**{k: v for k, v in item.items()
                                                if k in ContentAssetData.__dataclass_fields__}))
        return filtered[:limit]

    def _delete_json(self, uuid: str) -> bool:
        items = self._load_json()
        new_items = [i for i in items if i.get("uuid") != uuid]
        if len(new_items) < len(items):
            self._save_json_file(new_items)
            return True
        return False
