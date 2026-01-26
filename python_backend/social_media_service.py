"""
Social Media Manager Service for Mirai Skin

Manages Instagram content calendar (mirrored to Facebook),
generates content using AI, handles approval workflow,
publishes via Meta Graph API, and tracks organic performance.

Data is persisted to PostgreSQL database when available,
with JSON file fallback for local development.
"""

import os
import re
import json
import uuid as uuid_lib
import base64
import io
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

import httpx

# Lazy import OpenAI
OpenAI = None
def _get_openai_client(api_key: str = None):
    global OpenAI
    if OpenAI is None:
        from openai import OpenAI as _OpenAI
        OpenAI = _OpenAI
    return OpenAI(api_key=api_key)

DATABASE_AVAILABLE = bool(os.getenv("DATABASE_URL"))
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SOCIAL_DATA_FILE = os.path.join(DATA_DIR, "social_media.json")

META_GRAPH_URL = "https://graph.facebook.com/v21.0"
IG_GRAPH_URL = "https://graph.instagram.com/v21.0"


def compress_to_thumbnail(b64_data: str, max_size: int = 256) -> str:
    """Compress a base64 PNG image to a small JPEG thumbnail."""
    try:
        from PIL import Image as PILImage
        img_bytes = base64.b64decode(b64_data)
        img = PILImage.open(io.BytesIO(img_bytes))
        img.thumbnail((max_size, max_size), PILImage.LANCZOS)
        if img.mode == "RGBA":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[compress_to_thumbnail] Failed: {e}")
        return ""


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Strategy:
    id: str
    title: str
    description: str
    goals: List[str]
    content_mix: Dict[str, int]
    posting_frequency: Dict[str, Any]
    hashtag_strategy: Dict[str, Any]
    date_range_start: str
    date_range_end: str
    status: str  # draft, pending_review, approved, rejected, active, completed
    created_by: str
    created_at: str
    updated_at: str
    approved_by: Optional[int] = None
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    content_briefs: Optional[List[Dict]] = None


@dataclass
class Post:
    id: str
    strategy_id: Optional[str]
    post_type: str  # photo, reel, carousel, product_feature
    caption: str
    visual_direction: str
    status: str  # draft, pending_review, approved, scheduled, publishing, published, failed, rejected
    created_at: str
    updated_at: str
    content_category: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    product_ids: Optional[List[str]] = None
    link_url: Optional[str] = None
    utm_source: str = "instagram"
    utm_medium: str = "organic"
    utm_campaign: Optional[str] = None
    scheduled_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    ig_container_id: Optional[str] = None
    ig_media_id: Optional[str] = None
    fb_post_id: Optional[str] = None
    published_at: Optional[str] = None
    approved_by: Optional[int] = None
    approved_at: Optional[str] = None
    media_data: Optional[str] = None
    media_data_format: Optional[str] = None
    media_thumbnail: Optional[str] = None


@dataclass
class PostInsight:
    post_id: str
    ig_media_id: str
    impressions: int = 0
    reach: int = 0
    engagement: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    video_views: int = 0
    profile_visits: int = 0
    website_clicks: int = 0
    follower_delta: int = 0
    synced_at: Optional[str] = None


# ============================================================
# STORAGE — PostgreSQL with JSON fallback
# ============================================================

class SocialMediaStorage:
    def __init__(self):
        self.use_db = DATABASE_AVAILABLE
        if not self.use_db:
            os.makedirs(DATA_DIR, exist_ok=True)
            self._ensure_file_exists()
            print("[SocialMediaStorage] Using JSON file storage")
        else:
            print("[SocialMediaStorage] Using PostgreSQL database storage")

    def _ensure_file_exists(self):
        if not os.path.exists(SOCIAL_DATA_FILE):
            self._save_data({"strategies": [], "posts": [], "insights": [], "profile_cache": {}})

    def _load_data(self) -> Dict:
        try:
            with open(SOCIAL_DATA_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"strategies": [], "posts": [], "insights": [], "profile_cache": {}}

    def _save_data(self, data: Dict):
        with open(SOCIAL_DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    # ---------- Strategy CRUD ----------

    async def save_strategy_async(self, strategy: Strategy) -> str:
        if self.use_db:
            return await self._save_strategy_db(strategy)
        data = self._load_data()
        existing_idx = next((i for i, s in enumerate(data["strategies"]) if s["id"] == strategy.id), None)
        if existing_idx is not None:
            data["strategies"][existing_idx] = asdict(strategy)
        else:
            data["strategies"].append(asdict(strategy))
        self._save_data(data)
        return strategy.id

    async def get_strategy_async(self, strategy_id: str) -> Optional[Strategy]:
        if self.use_db:
            return await self._get_strategy_db(strategy_id)
        data = self._load_data()
        for s in data["strategies"]:
            if s["id"] == strategy_id:
                return Strategy(**s)
        return None

    async def get_all_strategies_async(self, status: Optional[str] = None) -> List[Strategy]:
        if self.use_db:
            return await self._get_all_strategies_db(status)
        data = self._load_data()
        strategies = [Strategy(**s) for s in data["strategies"]]
        if status:
            strategies = [s for s in strategies if s.status == status]
        return sorted(strategies, key=lambda x: x.created_at, reverse=True)

    # ---------- Post CRUD ----------

    async def save_post_async(self, post: Post) -> str:
        if self.use_db:
            return await self._save_post_db(post)
        data = self._load_data()
        existing_idx = next((i for i, p in enumerate(data["posts"]) if p["id"] == post.id), None)
        if existing_idx is not None:
            data["posts"][existing_idx] = asdict(post)
        else:
            data["posts"].append(asdict(post))
        self._save_data(data)
        return post.id

    async def get_post_async(self, post_id: str) -> Optional[Post]:
        if self.use_db:
            return await self._get_post_db(post_id)
        data = self._load_data()
        for p in data["posts"]:
            if p["id"] == post_id:
                return Post(**p)
        return None

    async def get_all_posts_async(self, status: Optional[str] = None, post_type: Optional[str] = None,
                                   strategy_id: Optional[str] = None,
                                   start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Post]:
        if self.use_db:
            return await self._get_all_posts_db(status, post_type, strategy_id, start_date, end_date)
        data = self._load_data()
        posts = [Post(**p) for p in data["posts"]]
        if status:
            posts = [p for p in posts if p.status == status]
        if post_type:
            posts = [p for p in posts if p.post_type == post_type]
        if strategy_id:
            posts = [p for p in posts if p.strategy_id == strategy_id]
        if start_date and end_date:
            posts = [p for p in posts if p.scheduled_at and start_date <= p.scheduled_at[:10] <= end_date]
        return sorted(posts, key=lambda x: x.scheduled_at or x.created_at, reverse=False)

    async def delete_post_async(self, post_id: str) -> bool:
        if self.use_db:
            return await self._delete_post_db(post_id)
        data = self._load_data()
        original_len = len(data["posts"])
        data["posts"] = [p for p in data["posts"] if p["id"] != post_id]
        if len(data["posts"]) < original_len:
            self._save_data(data)
            return True
        return False

    # ---------- Insights ----------

    async def save_insight_async(self, insight: PostInsight):
        if self.use_db:
            return await self._save_insight_db(insight)
        data = self._load_data()
        existing_idx = next((i for i, ins in enumerate(data["insights"]) if ins["post_id"] == insight.post_id), None)
        if existing_idx is not None:
            data["insights"][existing_idx] = asdict(insight)
        else:
            data["insights"].append(asdict(insight))
        self._save_data(data)

    async def get_insights_async(self, post_id: Optional[str] = None) -> List[PostInsight]:
        if self.use_db:
            return await self._get_insights_db(post_id)
        data = self._load_data()
        insights = [PostInsight(**i) for i in data["insights"]]
        if post_id:
            insights = [i for i in insights if i.post_id == post_id]
        return insights

    # ---------- Profile Cache ----------

    async def save_profile_cache_async(self, cache: Dict):
        if self.use_db:
            return await self._save_profile_cache_db(cache)
        data = self._load_data()
        data["profile_cache"] = cache
        self._save_data(data)

    async def get_profile_cache_async(self) -> Optional[Dict]:
        if self.use_db:
            return await self._get_profile_cache_db()
        data = self._load_data()
        return data.get("profile_cache") or None

    # ============================================================
    # ASYNC DATABASE METHODS
    # ============================================================

    async def _save_strategy_db(self, strategy: Strategy) -> str:
        from database.connection import get_db
        from database.models import SocialMediaStrategy
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(select(SocialMediaStrategy).where(SocialMediaStrategy.uuid == strategy.id))
            existing = result.scalar_one_or_none()

            if existing:
                existing.title = strategy.title
                existing.description = strategy.description
                existing.goals = strategy.goals
                existing.content_mix = strategy.content_mix
                existing.posting_frequency = strategy.posting_frequency
                existing.hashtag_strategy = strategy.hashtag_strategy
                existing.date_range_start = datetime.strptime(strategy.date_range_start, "%Y-%m-%d").date() if strategy.date_range_start else None
                existing.date_range_end = datetime.strptime(strategy.date_range_end, "%Y-%m-%d").date() if strategy.date_range_end else None
                existing.status = strategy.status
                existing.rejection_reason = strategy.rejection_reason
                existing.approved_by = strategy.approved_by
                existing.approved_at = datetime.fromisoformat(strategy.approved_at.replace("Z", "+00:00")).replace(tzinfo=None) if strategy.approved_at else None
                if strategy.content_briefs is not None:
                    existing.content_briefs = strategy.content_briefs
            else:
                db_strategy = SocialMediaStrategy(
                    uuid=strategy.id,
                    title=strategy.title,
                    description=strategy.description,
                    goals=strategy.goals,
                    content_mix=strategy.content_mix,
                    posting_frequency=strategy.posting_frequency,
                    hashtag_strategy=strategy.hashtag_strategy,
                    content_briefs=strategy.content_briefs,
                    date_range_start=datetime.strptime(strategy.date_range_start, "%Y-%m-%d").date() if strategy.date_range_start else None,
                    date_range_end=datetime.strptime(strategy.date_range_end, "%Y-%m-%d").date() if strategy.date_range_end else None,
                    status=strategy.status,
                    created_by=strategy.created_by,
                )
                db.add(db_strategy)
        return strategy.id

    async def _get_strategy_db(self, strategy_id: str) -> Optional[Strategy]:
        from database.connection import get_db
        from database.models import SocialMediaStrategy
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(select(SocialMediaStrategy).where(SocialMediaStrategy.uuid == strategy_id))
            s = result.scalar_one_or_none()
            if not s:
                return None
            return Strategy(
                id=s.uuid, title=s.title, description=s.description or "",
                goals=s.goals or [], content_mix=s.content_mix or {},
                posting_frequency=s.posting_frequency or {}, hashtag_strategy=s.hashtag_strategy or {},
                date_range_start=s.date_range_start.isoformat() if s.date_range_start else "",
                date_range_end=s.date_range_end.isoformat() if s.date_range_end else "",
                status=s.status, created_by=s.created_by or "",
                created_at=s.created_at.isoformat() + "Z" if s.created_at else "",
                updated_at=s.updated_at.isoformat() + "Z" if s.updated_at else "",
                approved_by=s.approved_by, rejection_reason=s.rejection_reason,
                approved_at=s.approved_at.isoformat() + "Z" if s.approved_at else None,
                content_briefs=s.content_briefs,
            )

    async def _get_all_strategies_db(self, status: Optional[str] = None) -> List[Strategy]:
        from database.connection import get_db
        from database.models import SocialMediaStrategy
        from sqlalchemy import select

        async with get_db() as db:
            query = select(SocialMediaStrategy).order_by(SocialMediaStrategy.created_at.desc())
            if status:
                query = query.where(SocialMediaStrategy.status == status)
            result = await db.execute(query)
            rows = result.scalars().all()
            return [Strategy(
                id=s.uuid, title=s.title, description=s.description or "",
                goals=s.goals or [], content_mix=s.content_mix or {},
                posting_frequency=s.posting_frequency or {}, hashtag_strategy=s.hashtag_strategy or {},
                date_range_start=s.date_range_start.isoformat() if s.date_range_start else "",
                date_range_end=s.date_range_end.isoformat() if s.date_range_end else "",
                status=s.status, created_by=s.created_by or "",
                created_at=s.created_at.isoformat() + "Z" if s.created_at else "",
                updated_at=s.updated_at.isoformat() + "Z" if s.updated_at else "",
                approved_by=s.approved_by, rejection_reason=s.rejection_reason,
                approved_at=s.approved_at.isoformat() + "Z" if s.approved_at else None,
                content_briefs=s.content_briefs,
            ) for s in rows]

    async def _save_post_db(self, post: Post) -> str:
        from database.connection import get_db
        from database.models import SocialMediaPost, SocialMediaStrategy
        from sqlalchemy import select

        async with get_db() as db:
            # Resolve strategy FK
            strategy_fk = None
            if post.strategy_id:
                r = await db.execute(select(SocialMediaStrategy.id).where(SocialMediaStrategy.uuid == post.strategy_id))
                row = r.scalar_one_or_none()
                if row:
                    strategy_fk = row

            result = await db.execute(select(SocialMediaPost).where(SocialMediaPost.uuid == post.id))
            existing = result.scalar_one_or_none()

            def _parse_dt(v):
                if not v:
                    return None
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    return None

            if existing:
                existing.post_type = post.post_type
                existing.content_category = post.content_category
                existing.caption = post.caption
                existing.visual_direction = post.visual_direction
                existing.media_url = post.media_url
                existing.media_type = post.media_type
                existing.product_ids = post.product_ids
                existing.link_url = post.link_url
                existing.utm_source = post.utm_source
                existing.utm_medium = post.utm_medium
                existing.utm_campaign = post.utm_campaign
                existing.scheduled_at = _parse_dt(post.scheduled_at)
                existing.status = post.status
                existing.rejection_reason = post.rejection_reason
                existing.ig_container_id = post.ig_container_id
                existing.ig_media_id = post.ig_media_id
                existing.fb_post_id = post.fb_post_id
                existing.published_at = _parse_dt(post.published_at)
                existing.approved_by = post.approved_by
                existing.approved_at = _parse_dt(post.approved_at)
                if post.media_data is not None:
                    existing.media_data = post.media_data
                if post.media_data_format is not None:
                    existing.media_data_format = post.media_data_format
                if post.media_thumbnail is not None:
                    existing.media_thumbnail = post.media_thumbnail
                if strategy_fk:
                    existing.strategy_id = strategy_fk
            else:
                db_post = SocialMediaPost(
                    uuid=post.id,
                    strategy_id=strategy_fk,
                    post_type=post.post_type,
                    content_category=post.content_category,
                    caption=post.caption,
                    visual_direction=post.visual_direction,
                    media_url=post.media_url,
                    media_type=post.media_type,
                    media_data=post.media_data,
                    media_data_format=post.media_data_format,
                    media_thumbnail=post.media_thumbnail,
                    product_ids=post.product_ids,
                    link_url=post.link_url,
                    utm_source=post.utm_source,
                    utm_medium=post.utm_medium,
                    utm_campaign=post.utm_campaign,
                    scheduled_at=_parse_dt(post.scheduled_at),
                    status=post.status,
                    rejection_reason=post.rejection_reason,
                    ig_container_id=post.ig_container_id,
                    ig_media_id=post.ig_media_id,
                    fb_post_id=post.fb_post_id,
                    published_at=_parse_dt(post.published_at),
                    approved_by=post.approved_by,
                    approved_at=_parse_dt(post.approved_at),
                )
                db.add(db_post)
        return post.id

    async def _get_post_db(self, post_id: str) -> Optional[Post]:
        from database.connection import get_db
        from database.models import SocialMediaPost, SocialMediaStrategy
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaPost).where(SocialMediaPost.uuid == post_id)
            )
            p = result.scalar_one_or_none()
            if not p:
                return None

            # Get strategy uuid
            strategy_uuid = None
            if p.strategy_id:
                r = await db.execute(select(SocialMediaStrategy.uuid).where(SocialMediaStrategy.id == p.strategy_id))
                strategy_uuid = r.scalar_one_or_none()

            return self._db_post_to_dataclass(p, strategy_uuid, include_media_data=True)

    def _db_post_to_dataclass(self, p, strategy_uuid=None, include_media_data=False) -> Post:
        return Post(
            id=p.uuid,
            strategy_id=strategy_uuid,
            post_type=p.post_type or "",
            caption=p.caption or "",
            visual_direction=p.visual_direction or "",
            status=p.status or "draft",
            content_category=getattr(p, 'content_category', None),
            created_at=p.created_at.isoformat() + "Z" if p.created_at else "",
            updated_at=p.updated_at.isoformat() + "Z" if p.updated_at else "",
            media_url=p.media_url,
            media_type=p.media_type,
            product_ids=p.product_ids,
            link_url=p.link_url,
            utm_source=p.utm_source or "instagram",
            utm_medium=p.utm_medium or "organic",
            utm_campaign=p.utm_campaign,
            scheduled_at=p.scheduled_at.isoformat() + "Z" if p.scheduled_at else None,
            rejection_reason=p.rejection_reason,
            ig_container_id=p.ig_container_id,
            ig_media_id=p.ig_media_id,
            fb_post_id=p.fb_post_id,
            published_at=p.published_at.isoformat() + "Z" if p.published_at else None,
            approved_by=p.approved_by,
            approved_at=p.approved_at.isoformat() + "Z" if p.approved_at else None,
            media_data=p.media_data if include_media_data else None,
            media_data_format=p.media_data_format,
            media_thumbnail=p.media_thumbnail,
        )

    async def _get_all_posts_db(self, status=None, post_type=None, strategy_id=None,
                                 start_date=None, end_date=None) -> List[Post]:
        from database.connection import get_db
        from database.models import SocialMediaPost, SocialMediaStrategy
        from sqlalchemy import select

        async with get_db() as db:
            query = select(SocialMediaPost).order_by(SocialMediaPost.scheduled_at.asc().nullslast())

            if status:
                query = query.where(SocialMediaPost.status == status)
            if post_type:
                query = query.where(SocialMediaPost.post_type == post_type)
            if strategy_id:
                r = await db.execute(select(SocialMediaStrategy.id).where(SocialMediaStrategy.uuid == strategy_id))
                fk = r.scalar_one_or_none()
                if fk:
                    query = query.where(SocialMediaPost.strategy_id == fk)
            if start_date:
                query = query.where(SocialMediaPost.scheduled_at >= datetime.fromisoformat(start_date))
            if end_date:
                query = query.where(SocialMediaPost.scheduled_at <= datetime.fromisoformat(end_date + "T23:59:59"))

            result = await db.execute(query)
            rows = result.scalars().all()

            # Batch resolve strategy uuids
            strategy_ids = {p.strategy_id for p in rows if p.strategy_id}
            strategy_map = {}
            if strategy_ids:
                r = await db.execute(
                    select(SocialMediaStrategy.id, SocialMediaStrategy.uuid)
                    .where(SocialMediaStrategy.id.in_(strategy_ids))
                )
                strategy_map = {row[0]: row[1] for row in r.all()}

            return [self._db_post_to_dataclass(p, strategy_map.get(p.strategy_id)) for p in rows]

    async def _delete_post_db(self, post_id: str) -> bool:
        from database.connection import get_db
        from database.models import SocialMediaPost
        from sqlalchemy import delete

        async with get_db() as db:
            result = await db.execute(
                delete(SocialMediaPost).where(SocialMediaPost.uuid == post_id)
            )
            return result.rowcount > 0

    async def _save_insight_db(self, insight: PostInsight):
        from database.connection import get_db
        from database.models import SocialMediaInsight, SocialMediaPost
        from sqlalchemy import select

        async with get_db() as db:
            r = await db.execute(select(SocialMediaPost.id).where(SocialMediaPost.uuid == insight.post_id))
            post_fk = r.scalar_one_or_none()
            if not post_fk:
                return

            result = await db.execute(
                select(SocialMediaInsight).where(SocialMediaInsight.post_id == post_fk)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.ig_media_id = insight.ig_media_id
                existing.impressions = insight.impressions
                existing.reach = insight.reach
                existing.engagement = insight.engagement
                existing.likes = insight.likes
                existing.comments = insight.comments
                existing.shares = insight.shares
                existing.saves = insight.saves
                existing.video_views = insight.video_views
                existing.profile_visits = insight.profile_visits
                existing.website_clicks = insight.website_clicks
                existing.follower_delta = insight.follower_delta
                existing.synced_at = datetime.utcnow()
            else:
                db.add(SocialMediaInsight(
                    post_id=post_fk,
                    ig_media_id=insight.ig_media_id,
                    impressions=insight.impressions,
                    reach=insight.reach,
                    engagement=insight.engagement,
                    likes=insight.likes,
                    comments=insight.comments,
                    shares=insight.shares,
                    saves=insight.saves,
                    video_views=insight.video_views,
                    profile_visits=insight.profile_visits,
                    website_clicks=insight.website_clicks,
                    follower_delta=insight.follower_delta,
                ))

    async def _get_insights_db(self, post_id: Optional[str] = None) -> List[PostInsight]:
        from database.connection import get_db
        from database.models import SocialMediaInsight, SocialMediaPost
        from sqlalchemy import select

        async with get_db() as db:
            query = select(SocialMediaInsight)
            if post_id:
                r = await db.execute(select(SocialMediaPost.id).where(SocialMediaPost.uuid == post_id))
                post_fk = r.scalar_one_or_none()
                if not post_fk:
                    return []
                query = query.where(SocialMediaInsight.post_id == post_fk)

            result = await db.execute(query)
            rows = result.scalars().all()

            # Resolve post uuids
            post_ids = {row.post_id for row in rows}
            post_map = {}
            if post_ids:
                r = await db.execute(
                    select(SocialMediaPost.id, SocialMediaPost.uuid)
                    .where(SocialMediaPost.id.in_(post_ids))
                )
                post_map = {row[0]: row[1] for row in r.all()}

            return [PostInsight(
                post_id=post_map.get(row.post_id, ""),
                ig_media_id=row.ig_media_id or "",
                impressions=row.impressions or 0,
                reach=row.reach or 0,
                engagement=row.engagement or 0,
                likes=row.likes or 0,
                comments=row.comments or 0,
                shares=row.shares or 0,
                saves=row.saves or 0,
                video_views=row.video_views or 0,
                profile_visits=row.profile_visits or 0,
                website_clicks=row.website_clicks or 0,
                follower_delta=row.follower_delta or 0,
                synced_at=row.synced_at.isoformat() + "Z" if row.synced_at else None,
            ) for row in rows]

    async def _save_profile_cache_db(self, cache: Dict):
        from database.connection import get_db
        from database.models import SocialMediaProfileCache
        from sqlalchemy import select

        ig_account_id = cache.get("ig_account_id", "default")

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaProfileCache).where(SocialMediaProfileCache.ig_account_id == ig_account_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.followers_count = cache.get("followers_count", 0)
                existing.media_count = cache.get("media_count", 0)
                existing.recent_captions = cache.get("recent_captions")
                existing.brand_voice_analysis = cache.get("brand_voice_analysis")
                existing.best_posting_times = cache.get("best_posting_times")
                existing.top_hashtags = cache.get("top_hashtags")
                existing.synced_at = datetime.utcnow()
            else:
                db.add(SocialMediaProfileCache(
                    ig_account_id=ig_account_id,
                    followers_count=cache.get("followers_count", 0),
                    media_count=cache.get("media_count", 0),
                    recent_captions=cache.get("recent_captions"),
                    brand_voice_analysis=cache.get("brand_voice_analysis"),
                    best_posting_times=cache.get("best_posting_times"),
                    top_hashtags=cache.get("top_hashtags"),
                ))

    async def _get_profile_cache_db(self) -> Optional[Dict]:
        from database.connection import get_db
        from database.models import SocialMediaProfileCache
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaProfileCache).order_by(SocialMediaProfileCache.synced_at.desc()).limit(1)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "ig_account_id": row.ig_account_id,
                "followers_count": row.followers_count,
                "media_count": row.media_count,
                "recent_captions": row.recent_captions,
                "brand_voice_analysis": row.brand_voice_analysis,
                "best_posting_times": row.best_posting_times,
                "top_hashtags": row.top_hashtags,
                "synced_at": row.synced_at.isoformat() + "Z" if row.synced_at else None,
            }

    # ---------- Account Snapshots ----------

    async def save_account_snapshot_async(self, snapshot: Dict):
        """Save daily account-level metrics snapshot."""
        if not self.use_db:
            # JSON fallback: append to snapshots list
            data = self._load_data()
            data.setdefault("account_snapshots", [])
            # Replace existing for same date
            data["account_snapshots"] = [
                s for s in data["account_snapshots"]
                if s.get("date") != snapshot.get("date")
            ]
            data["account_snapshots"].append(snapshot)
            self._save_data(data)
            return

        from database.connection import get_db
        from database.models import SocialMediaAccountSnapshot
        from sqlalchemy import select

        async with get_db() as db:
            snap_date = datetime.strptime(snapshot["date"], "%Y-%m-%d").date() if isinstance(snapshot["date"], str) else snapshot["date"]
            ig_id = snapshot.get("ig_account_id", "default")

            result = await db.execute(
                select(SocialMediaAccountSnapshot).where(
                    SocialMediaAccountSnapshot.date == snap_date,
                    SocialMediaAccountSnapshot.ig_account_id == ig_id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                for key in ["impressions", "reach", "profile_views", "website_clicks",
                            "follower_count", "follows", "unfollows",
                            "total_likes", "total_comments", "total_shares", "total_saves",
                            "posts_published", "stories_published", "reels_published",
                            "online_followers"]:
                    if key in snapshot:
                        setattr(existing, key, snapshot[key])
                existing.synced_at = datetime.utcnow()
            else:
                db.add(SocialMediaAccountSnapshot(
                    date=snap_date,
                    ig_account_id=ig_id,
                    impressions=snapshot.get("impressions", 0),
                    reach=snapshot.get("reach", 0),
                    profile_views=snapshot.get("profile_views", 0),
                    website_clicks=snapshot.get("website_clicks", 0),
                    follower_count=snapshot.get("follower_count", 0),
                    follows=snapshot.get("follows", 0),
                    unfollows=snapshot.get("unfollows", 0),
                    total_likes=snapshot.get("total_likes", 0),
                    total_comments=snapshot.get("total_comments", 0),
                    total_shares=snapshot.get("total_shares", 0),
                    total_saves=snapshot.get("total_saves", 0),
                    posts_published=snapshot.get("posts_published", 0),
                    stories_published=snapshot.get("stories_published", 0),
                    reels_published=snapshot.get("reels_published", 0),
                    online_followers=snapshot.get("online_followers"),
                ))

    async def get_account_snapshots_async(self, start_date: str, end_date: str) -> List[Dict]:
        """Get account snapshots for a date range."""
        if not self.use_db:
            data = self._load_data()
            snapshots = data.get("account_snapshots", [])
            return [s for s in snapshots if start_date <= s.get("date", "") <= end_date]

        from database.connection import get_db
        from database.models import SocialMediaAccountSnapshot
        from sqlalchemy import select

        async with get_db() as db:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()

            result = await db.execute(
                select(SocialMediaAccountSnapshot)
                .where(SocialMediaAccountSnapshot.date >= sd)
                .where(SocialMediaAccountSnapshot.date <= ed)
                .order_by(SocialMediaAccountSnapshot.date.asc())
            )
            rows = result.scalars().all()

            return [{
                "date": row.date.isoformat(),
                "ig_account_id": row.ig_account_id,
                "impressions": row.impressions or 0,
                "reach": row.reach or 0,
                "profile_views": row.profile_views or 0,
                "website_clicks": row.website_clicks or 0,
                "follower_count": row.follower_count or 0,
                "follows": row.follows or 0,
                "unfollows": row.unfollows or 0,
                "total_likes": row.total_likes or 0,
                "total_comments": row.total_comments or 0,
                "total_shares": row.total_shares or 0,
                "total_saves": row.total_saves or 0,
                "posts_published": row.posts_published or 0,
                "stories_published": row.stories_published or 0,
                "reels_published": row.reels_published or 0,
                "online_followers": row.online_followers,
            } for row in rows]

    # ---------- Connection management ----------

    async def save_connection_async(self, connection_data: Dict) -> int:
        """Save or update a Meta/Instagram connection in the database."""
        if not self.use_db:
            # File-based fallback
            data = self._load_data()
            data["connection"] = connection_data
            self._save_data(data)
            return 1

        from database.connection import get_db
        from database.models import SocialMediaConnection
        from sqlalchemy import select

        async with get_db() as db:
            # Deactivate existing connections for this platform
            existing = await db.execute(
                select(SocialMediaConnection).where(
                    SocialMediaConnection.platform == connection_data.get("platform", "instagram"),
                    SocialMediaConnection.is_active == True
                )
            )
            for row in existing.scalars().all():
                row.is_active = False

            # Create new connection
            conn = SocialMediaConnection(
                platform=connection_data.get("platform", "instagram"),
                access_token=connection_data["access_token"],
                page_id=connection_data.get("page_id"),
                ig_account_id=connection_data.get("ig_account_id"),
                ig_username=connection_data.get("ig_username"),
                ig_followers=connection_data.get("ig_followers", 0),
                ig_profile_pic=connection_data.get("ig_profile_pic"),
                token_expires_at=connection_data.get("token_expires_at"),
                token_type=connection_data.get("token_type", "long_lived"),
                is_active=True,
                last_validated_at=datetime.utcnow(),
            )
            db.add(conn)
            await db.flush()
            return conn.id

    async def get_active_connection_async(self, platform: str = "instagram") -> Optional[Dict]:
        """Get the active connection for a platform."""
        if not self.use_db:
            data = self._load_data()
            return data.get("connection")

        from database.connection import get_db
        from database.models import SocialMediaConnection
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaConnection).where(
                    SocialMediaConnection.platform == platform,
                    SocialMediaConnection.is_active == True
                ).order_by(SocialMediaConnection.id.desc()).limit(1)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "id": row.id,
                "platform": row.platform,
                "access_token": row.access_token,
                "page_id": row.page_id,
                "ig_account_id": row.ig_account_id,
                "ig_username": row.ig_username,
                "ig_followers": row.ig_followers or 0,
                "ig_profile_pic": row.ig_profile_pic,
                "token_expires_at": row.token_expires_at.isoformat() if row.token_expires_at else None,
                "token_type": row.token_type,
                "is_active": row.is_active,
                "connected_at": row.connected_at.isoformat() if row.connected_at else None,
                "last_validated_at": row.last_validated_at.isoformat() if row.last_validated_at else None,
            }

    async def update_connection_async(self, connection_id: int, updates: Dict):
        """Update fields on an existing connection."""
        if not self.use_db:
            data = self._load_data()
            if data.get("connection"):
                data["connection"].update(updates)
                self._save_data(data)
            return

        from database.connection import get_db
        from database.models import SocialMediaConnection
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaConnection).where(SocialMediaConnection.id == connection_id)
            )
            row = result.scalar_one_or_none()
            if row:
                for key, value in updates.items():
                    if hasattr(row, key):
                        setattr(row, key, value)

    async def disconnect_async(self, platform: str = "instagram"):
        """Deactivate all connections for a platform."""
        if not self.use_db:
            data = self._load_data()
            data.pop("connection", None)
            self._save_data(data)
            return

        from database.connection import get_db
        from database.models import SocialMediaConnection
        from sqlalchemy import select

        async with get_db() as db:
            result = await db.execute(
                select(SocialMediaConnection).where(
                    SocialMediaConnection.platform == platform,
                    SocialMediaConnection.is_active == True
                )
            )
            for row in result.scalars().all():
                row.is_active = False


# ============================================================
# META TOKEN MANAGEMENT
# ============================================================

async def validate_meta_token(access_token: str) -> Dict:
    """Validate a Meta access token and return its info (expiry, scopes, etc.).
    Supports both IGAA (Instagram) and EAA (Facebook) tokens."""
    is_ig_token = access_token.startswith("IGAA")

    async with httpx.AsyncClient(timeout=30) as client:
        if is_ig_token:
            # For Instagram tokens, validate by calling /me with minimal fields
            resp = await client.get(
                f"{IG_GRAPH_URL}/me",
                params={"fields": "user_id,username", "access_token": access_token}
            )
            if resp.status_code != 200:
                err_detail = ""
                try:
                    err_detail = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err_detail = resp.text[:200]
                return {"valid": False, "error": f"Instagram token validation failed: {err_detail}"}

            ig_data = resp.json()
            return {
                "valid": True,
                "app_id": "",
                "scopes": ["instagram_basic", "instagram_content_publish", "instagram_manage_insights"],
                "expires_at": None,
                "expires_at_ts": 0,
                "is_expired": False,
                "token_type": "instagram",
                "days_until_expiry": None,  # IG tokens from app dashboard don't expire easily
                "ig_username": ig_data.get("username"),
                "ig_user_id": ig_data.get("user_id"),
            }

        # Facebook (EAA) token — use debug_token
        resp = await client.get(
            f"{META_GRAPH_URL}/debug_token",
            params={"input_token": access_token, "access_token": access_token}
        )
        if resp.status_code != 200:
            return {"valid": False, "error": f"Token validation failed (HTTP {resp.status_code})"}

        data = resp.json().get("data", {})
        is_valid = data.get("is_valid", False)
        expires_at = data.get("expires_at", 0)
        scopes = data.get("scopes", [])
        app_id = data.get("app_id", "")

        result = {
            "valid": is_valid,
            "app_id": app_id,
            "scopes": scopes,
            "expires_at": datetime.utcfromtimestamp(expires_at).isoformat() if expires_at else None,
            "expires_at_ts": expires_at,
            "is_expired": expires_at > 0 and datetime.utcfromtimestamp(expires_at) < datetime.utcnow(),
            "token_type": data.get("type", "unknown"),
        }

        if expires_at and expires_at > 0:
            expires_dt = datetime.utcfromtimestamp(expires_at)
            days_left = (expires_dt - datetime.utcnow()).days
            result["days_until_expiry"] = days_left
        else:
            result["days_until_expiry"] = None

        return result


async def exchange_for_long_lived_token(short_token: str) -> Dict:
    """Exchange a short-lived token for a long-lived one (~60 days).
    Requires META_APP_ID/APP_ID and META_APP_SECRET/APP_SECRET env vars."""
    app_id = os.getenv("META_APP_ID") or os.getenv("APP_ID")
    app_secret = os.getenv("META_APP_SECRET") or os.getenv("APP_SECRET")
    if not app_id or not app_secret:
        return {"error": "META_APP_ID and META_APP_SECRET (or APP_ID/APP_SECRET) required for token exchange"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{META_GRAPH_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            }
        )
        if resp.status_code != 200:
            return {"error": f"Token exchange failed: {resp.text}"}

        data = resp.json()
        return {
            "access_token": data.get("access_token"),
            "token_type": "long_lived",
            "expires_in": data.get("expires_in"),  # seconds (~5184000 = 60 days)
        }


async def refresh_long_lived_token(current_token: str) -> Dict:
    """Refresh a long-lived token to get a new one with extended expiry.
    Only works if the current token is still valid and not expired."""
    app_id = os.getenv("META_APP_ID") or os.getenv("APP_ID")
    app_secret = os.getenv("META_APP_SECRET") or os.getenv("APP_SECRET")
    if not app_id or not app_secret:
        return {"error": "META_APP_ID and META_APP_SECRET (or APP_ID/APP_SECRET) required for token refresh"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{META_GRAPH_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": current_token,
            }
        )
        if resp.status_code != 200:
            return {"error": f"Token refresh failed: {resp.text}"}

        data = resp.json()
        return {
            "access_token": data.get("access_token"),
            "token_type": "long_lived",
            "expires_in": data.get("expires_in"),
        }


async def fetch_ig_account_from_token(access_token: str, page_id: str) -> Dict:
    """Given a valid token and page ID, fetch the linked Instagram Business Account info.
    Supports both IGAA (Instagram API) and EAA (Facebook Graph API) tokens."""
    is_ig_token = access_token.startswith("IGAA")

    async with httpx.AsyncClient(timeout=30) as client:
        if is_ig_token:
            # Instagram API token — fetch directly from /me
            # Try full fields first, fall back to minimal if API rejects some fields
            full_fields = "user_id,username,followers_count,media_count,profile_picture_url,biography"
            resp = await client.get(
                f"{IG_GRAPH_URL}/me",
                params={"fields": full_fields, "access_token": access_token}
            )
            if resp.status_code != 200:
                # Retry with minimal fields
                resp = await client.get(
                    f"{IG_GRAPH_URL}/me",
                    params={"fields": "user_id,username", "access_token": access_token}
                )
            if resp.status_code != 200:
                err_detail = ""
                try:
                    err_detail = resp.json().get("error", {}).get("message", resp.text[:300])
                except Exception:
                    err_detail = resp.text[:300]
                return {"error": f"Failed to fetch IG profile: {err_detail}"}

            ig_data = resp.json()
            return {
                "ig_account_id": ig_data.get("user_id", ig_data.get("id")),
                "ig_username": ig_data.get("username"),
                "ig_followers": ig_data.get("followers_count", 0),
                "ig_media_count": ig_data.get("media_count", 0),
                "ig_profile_pic": ig_data.get("profile_picture_url"),
                "ig_biography": ig_data.get("biography"),
                "page_name": None,
            }

        # Facebook (EAA) token — look up IG account via Page
        resp = await client.get(
            f"{META_GRAPH_URL}/{page_id}",
            params={"fields": "instagram_business_account,name,picture", "access_token": access_token}
        )
        if resp.status_code != 200:
            return {"error": f"Failed to fetch page info: {resp.text}"}

        page_data = resp.json()
        ig_biz = page_data.get("instagram_business_account", {})
        ig_id = ig_biz.get("id")
        if not ig_id:
            return {"error": "No Instagram Business Account linked to this Facebook Page. Ensure you have a Professional (Business or Creator) Instagram account connected to this Page."}

        resp2 = await client.get(
            f"{META_GRAPH_URL}/{ig_id}",
            params={"fields": "username,followers_count,media_count,profile_picture_url,biography", "access_token": access_token}
        )
        if resp2.status_code != 200:
            return {"error": f"Failed to fetch IG profile: {resp2.text}"}

        ig_data = resp2.json()
        return {
            "ig_account_id": ig_id,
            "ig_username": ig_data.get("username"),
            "ig_followers": ig_data.get("followers_count", 0),
            "ig_media_count": ig_data.get("media_count", 0),
            "ig_profile_pic": ig_data.get("profile_picture_url"),
            "ig_biography": ig_data.get("biography"),
            "page_name": page_data.get("name"),
        }


# ============================================================
# INSTAGRAM PUBLISHER — Meta Content Publishing API
# ============================================================

class InstagramPublisher:
    def __init__(self, access_token: Optional[str] = None, page_id: Optional[str] = None,
                 ig_account_id: Optional[str] = None):
        self.access_token = access_token or os.getenv("IG_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
        self.page_id = page_id or os.getenv("META_PAGE_ID")
        self._ig_account_id = ig_account_id or os.getenv("META_IG_ACCOUNT_ID")
        if not self.access_token:
            raise ValueError("META_ACCESS_TOKEN not configured")
        # Detect token type: IGAA = Instagram API, EAA = Facebook Graph API
        self.is_ig_token = self.access_token.startswith("IGAA")
        self.base_url = IG_GRAPH_URL if self.is_ig_token else META_GRAPH_URL

    async def _request(self, method: str, url: str, **kwargs) -> Dict:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def get_ig_account_id(self) -> str:
        if self._ig_account_id:
            return self._ig_account_id
        if self.is_ig_token:
            # For IG tokens, fetch user_id from /me endpoint
            data = await self._request("GET", f"{IG_GRAPH_URL}/me",
                                        params={"fields": "user_id,username", "access_token": self.access_token})
            self._ig_account_id = data.get("user_id", data.get("id"))
            return self._ig_account_id
        # For Facebook tokens, look up via Page
        data = await self._request("GET", f"{META_GRAPH_URL}/{self.page_id}",
                                    params={"fields": "instagram_business_account", "access_token": self.access_token})
        ig = data.get("instagram_business_account", {}).get("id")
        if not ig:
            raise ValueError("No Instagram Business Account linked to this Page")
        self._ig_account_id = ig
        return ig

    async def get_profile_info(self, ig_account_id: str) -> Dict:
        fields = "followers_count,media_count,username,biography"
        if self.is_ig_token:
            fields = "user_id,username,followers_count,media_count,biography,profile_picture_url"
        data = await self._request("GET", f"{self.base_url}/{ig_account_id}",
                                    params={"fields": fields,
                                            "access_token": self.access_token})
        return data

    async def get_recent_media(self, ig_account_id: str, limit: int = 25) -> List[Dict]:
        fields = "caption,timestamp,media_type,like_count,comments_count,permalink"
        data = await self._request("GET", f"{self.base_url}/{ig_account_id}/media",
                                    params={"fields": fields,
                                            "limit": limit, "access_token": self.access_token})
        return data.get("data", [])

    async def create_image_container(self, ig_account_id: str, image_url: str, caption: str) -> str:
        data = await self._request("POST", f"{self.base_url}/{ig_account_id}/media",
                                    data={"image_url": image_url, "caption": caption,
                                          "access_token": self.access_token})
        return data["id"]

    async def create_reel_container(self, ig_account_id: str, video_url: str, caption: str) -> str:
        data = await self._request("POST", f"{self.base_url}/{ig_account_id}/media",
                                    data={"video_url": video_url, "caption": caption,
                                          "media_type": "REELS", "access_token": self.access_token})
        return data["id"]

    async def create_story_container(self, ig_account_id: str, image_url: str) -> str:
        """Create an Instagram Story container (no caption for stories)"""
        data = await self._request("POST", f"{self.base_url}/{ig_account_id}/media",
                                    data={"image_url": image_url, "media_type": "STORIES",
                                          "access_token": self.access_token})
        return data["id"]

    async def create_carousel_container(self, ig_account_id: str, children_ids: List[str], caption: str) -> str:
        data = await self._request("POST", f"{self.base_url}/{ig_account_id}/media",
                                    data={"media_type": "CAROUSEL", "caption": caption,
                                          "children": ",".join(children_ids),
                                          "access_token": self.access_token})
        return data["id"]

    async def check_container_status(self, container_id: str) -> str:
        data = await self._request("GET", f"{self.base_url}/{container_id}",
                                    params={"fields": "status_code", "access_token": self.access_token})
        return data.get("status_code", "IN_PROGRESS")

    async def publish_container(self, ig_account_id: str, container_id: str) -> str:
        data = await self._request("POST", f"{self.base_url}/{ig_account_id}/media_publish",
                                    data={"creation_id": container_id, "access_token": self.access_token})
        return data["id"]

    async def mirror_to_facebook(self, message: str, link: Optional[str] = None,
                                  media_url: Optional[str] = None) -> Optional[str]:
        """Mirror post to Facebook Page. Only works with Facebook (EAA) tokens."""
        if self.is_ig_token or not self.page_id:
            print("[InstagramPublisher] Skipping Facebook mirror (IG token or no page_id)")
            return None
        try:
            if media_url:
                data = await self._request("POST", f"{META_GRAPH_URL}/{self.page_id}/photos",
                                            data={"url": media_url, "message": message,
                                                  "access_token": self.access_token})
            else:
                payload = {"message": message, "access_token": self.access_token}
                if link:
                    payload["link"] = link
                data = await self._request("POST", f"{META_GRAPH_URL}/{self.page_id}/feed", data=payload)
            return data.get("id")
        except Exception as e:
            print(f"[InstagramPublisher] Facebook mirror failed: {e}")
            return None

    async def fetch_account_insights(self, ig_account_id: str, since: date, until: date) -> List[Dict]:
        """Fetch account-level daily insights from Instagram Insights API.
        Returns a list of daily metric dicts for the date range."""
        results = []
        try:
            since_ts = int(datetime.combine(since, datetime.min.time()).timestamp())
            until_ts = int(datetime.combine(until + timedelta(days=1), datetime.min.time()).timestamp())

            # IG API uses different metric names than Facebook Graph API
            if self.is_ig_token:
                metrics = "reach,follower_count,profile_views,website_clicks"
            else:
                metrics = "impressions,reach,profile_views,website_clicks,follower_count"
            data = await self._request("GET", f"{self.base_url}/{ig_account_id}/insights",
                                        params={"metric": metrics, "period": "day",
                                                "since": since_ts, "until": until_ts,
                                                "access_token": self.access_token})

            daily_map = {}
            for metric_data in data.get("data", []):
                metric_name = metric_data["name"]
                for val in metric_data.get("values", []):
                    end_time = val.get("end_time", "")[:10]
                    if end_time not in daily_map:
                        daily_map[end_time] = {"date": end_time}
                    daily_map[end_time][metric_name] = val.get("value", 0)

            results = sorted(daily_map.values(), key=lambda d: d["date"])
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch account insights: {e}")

        return results

    async def fetch_account_demographics(self, ig_account_id: str) -> Dict:
        """Fetch audience demographics."""
        try:
            if self.is_ig_token:
                metrics = "follower_demographics"
                period = "lifetime"
            else:
                metrics = "audience_city,audience_country,audience_gender_age"
                period = "lifetime"
            data = await self._request("GET", f"{self.base_url}/{ig_account_id}/insights",
                                        params={"metric": metrics, "period": period,
                                                "access_token": self.access_token})
            result = {}
            for item in data.get("data", []):
                result[item["name"]] = item["values"][0]["value"] if item.get("values") else {}
            return result
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch demographics: {e}")
            return {}

    async def fetch_online_followers(self, ig_account_id: str) -> Dict:
        """Fetch online followers distribution by hour."""
        try:
            data = await self._request("GET", f"{self.base_url}/{ig_account_id}/insights",
                                        params={"metric": "online_followers",
                                                "period": "lifetime",
                                                "access_token": self.access_token})
            for item in data.get("data", []):
                if item["name"] == "online_followers":
                    return item["values"][0]["value"] if item.get("values") else {}
            return {}
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch online followers: {e}")
            return {}

    async def fetch_recent_media_detailed(self, ig_account_id: str, limit: int = 50) -> List[Dict]:
        """Fetch recent media with full engagement metrics."""
        try:
            fields = "id,caption,timestamp,media_type,like_count,comments_count,permalink"
            if not self.is_ig_token:
                fields += ",media_url,thumbnail_url"
            data = await self._request("GET", f"{self.base_url}/{ig_account_id}/media",
                                        params={"fields": fields,
                                                "limit": limit, "access_token": self.access_token})
            media_list = data.get("data", [])

            for media in media_list:
                try:
                    insights = await self.fetch_post_insights(media["id"])
                    media["insights"] = insights
                except Exception:
                    media["insights"] = {}

            return media_list
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch detailed media: {e}")
            return []

    async def fetch_post_insights(self, ig_media_id: str) -> Dict:
        try:
            if self.is_ig_token:
                metrics = "reach,saved,shares,likes,comments,total_interactions"
            else:
                metrics = "impressions,reach,saved,shares,likes,comments,total_interactions"
            data = await self._request("GET", f"{self.base_url}/{ig_media_id}/insights",
                                        params={"metric": metrics,
                                                "access_token": self.access_token})
            metrics_dict = {}
            for item in data.get("data", []):
                metrics_dict[item["name"]] = item["values"][0]["value"] if item.get("values") else 0
            return metrics_dict
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch insights for {ig_media_id}: {e}")
            return {}


# ============================================================
# SOCIAL MEDIA AI AGENT
# ============================================================

class SocialMediaAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        # OpenAI client created lazily — only needed for DALL-E
        self._openai_client = None
        if not self.gemini_api_key and not self.api_key:
            raise ValueError("GEMINI_API_KEY or OPENAI_API_KEY must be configured")
        self.storage = SocialMediaStorage()

    @property
    def client(self):
        """Lazy OpenAI client — only created when DALL-E is needed."""
        if self._openai_client is None:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY required for DALL-E. Set OPENAI_API_KEY env var.")
            self._openai_client = _get_openai_client(api_key=self.api_key)
        return self._openai_client

    def _call_ai(self, system_prompt: str, user_prompt: str, json_mode: bool = True, max_tokens: int = 4000) -> str:
        """Generate text using Gemini (preferred) or OpenAI GPT-4o (fallback)."""
        if self.gemini_api_key:
            result = self._call_gemini(system_prompt, user_prompt, json_mode, max_tokens)
            if result:
                return result
            print("[SocialMediaAgent] Gemini text generation failed, falling back to GPT-4o")

        if not self.api_key:
            raise ValueError("No AI API key available for text generation")

        kwargs = {"model": "gpt-4o", "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], "temperature": 0.7, "max_tokens": max_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def _call_gemini(self, system_prompt: str, user_prompt: str, json_mode: bool = True, max_tokens: int = 4000) -> Optional[str]:
        """Call Google Gemini for text generation."""
        try:
            gen_config = {
                "temperature": 0.7,
                "maxOutputTokens": max_tokens,
            }
            if json_mode:
                gen_config["responseMimeType"] = "application/json"

            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": gen_config,
            }

            resp = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": self.gemini_api_key},
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=90,
            )

            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            print("[SocialMediaAgent] Text generated via Gemini")
                            return text

            print(f"[SocialMediaAgent] Gemini text failed (HTTP {resp.status_code}): {resp.text[:300]}")
            return None
        except Exception as e:
            print(f"[SocialMediaAgent] Gemini text error: {e}")
            return None

    async def sync_product_catalog(self) -> List[Dict]:
        """Fetch full product catalog from Shopify and upsert into DB.
        Returns list of product dicts for passing to AI prompts."""
        from shopify_client import fetch_product_catalog

        raw_products = fetch_product_catalog()
        product_dicts = []

        if DATABASE_AVAILABLE:
            from database.connection import get_db
            from database.models import Product
            from sqlalchemy import select
            from decimal import Decimal

            async with get_db() as db:
                for p in raw_products:
                    gid = p.get("id", "")
                    # Extract variant prices
                    variant_edges = (p.get("variants") or {}).get("edges") or []
                    prices = []
                    for ve in variant_edges:
                        vn = ve.get("node") or {}
                        pr = vn.get("price")
                        if pr:
                            try:
                                prices.append(float(pr))
                            except (ValueError, TypeError):
                                pass

                    price_min = Decimal(str(min(prices))) if prices else None
                    price_max = Decimal(str(max(prices))) if prices else None

                    # Extract images
                    image_edges = (p.get("images") or {}).get("edges") or []
                    images_list = [{"url": ie["node"]["url"], "altText": ie["node"].get("altText")}
                                   for ie in image_edges if ie.get("node", {}).get("url")]

                    featured_img = (p.get("featuredImage") or {}).get("url")

                    result = await db.execute(select(Product).where(Product.shopify_gid == gid))
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.title = p.get("title", existing.title)
                        existing.description = p.get("description")
                        existing.handle = p.get("handle")
                        existing.product_type = p.get("productType")
                        existing.vendor = p.get("vendor")
                        existing.tags = p.get("tags")
                        existing.featured_image_url = featured_img
                        existing.images = images_list
                        existing.price_min = price_min
                        existing.price_max = price_max
                        existing.status = (p.get("status") or "").lower()
                    else:
                        db.add(Product(
                            shopify_gid=gid,
                            title=p.get("title", ""),
                            description=p.get("description"),
                            handle=p.get("handle"),
                            product_type=p.get("productType"),
                            vendor=p.get("vendor"),
                            tags=p.get("tags"),
                            featured_image_url=featured_img,
                            images=images_list,
                            price_min=price_min,
                            price_max=price_max,
                            status=(p.get("status") or "").lower(),
                        ))

                    product_dicts.append({
                        "shopify_gid": gid,
                        "title": p.get("title", ""),
                        "handle": p.get("handle", ""),
                        "description": (p.get("description") or "")[:200],
                        "product_type": p.get("productType", ""),
                        "tags": p.get("tags", []),
                        "price_min": float(price_min) if price_min else None,
                        "price_max": float(price_max) if price_max else None,
                        "featured_image_url": featured_img,
                        "status": (p.get("status") or "").lower(),
                    })
        else:
            # No DB — just return dicts from Shopify
            for p in raw_products:
                variant_edges = (p.get("variants") or {}).get("edges") or []
                prices = []
                for ve in variant_edges:
                    pr = (ve.get("node") or {}).get("price")
                    if pr:
                        try:
                            prices.append(float(pr))
                        except (ValueError, TypeError):
                            pass

                product_dicts.append({
                    "shopify_gid": p.get("id", ""),
                    "title": p.get("title", ""),
                    "handle": p.get("handle", ""),
                    "description": (p.get("description") or "")[:200],
                    "product_type": p.get("productType", ""),
                    "tags": p.get("tags", []),
                    "price_min": min(prices) if prices else None,
                    "price_max": max(prices) if prices else None,
                    "featured_image_url": (p.get("featuredImage") or {}).get("url"),
                    "status": (p.get("status") or "").lower(),
                })

        print(f"[SocialMediaAgent] Synced {len(product_dicts)} products from Shopify")
        return product_dicts

    async def analyze_brand_voice(self, ig_account_id: Optional[str] = None) -> Dict:
        """Fetch recent IG posts and analyze brand voice with AI"""
        captions = []
        profile_info = {}

        try:
            publisher = InstagramPublisher()
            if not ig_account_id:
                ig_account_id = await publisher.get_ig_account_id()
            profile_info = await publisher.get_profile_info(ig_account_id)
            recent_media = await publisher.get_recent_media(ig_account_id, limit=25)
            captions = [m.get("caption", "") for m in recent_media if m.get("caption")]
        except Exception as e:
            print(f"[SocialMediaAgent] Could not fetch IG data: {e}")

        if not captions:
            captions = ["(No captions available — use general K-Beauty brand voice)"]

        system_prompt = """You are a social media brand strategist. Analyze the following Instagram captions
and provide a comprehensive brand voice guide. Return valid JSON."""

        user_prompt = f"""Analyze these Instagram captions for brand voice, tone, language patterns,
emoji usage, hashtag style, and CTA patterns. Provide a brand voice guide.

CAPTIONS:
{json.dumps(captions[:25], indent=2)}

Return JSON:
{{
  "tone": "description of overall tone",
  "language_style": "description of language patterns",
  "emoji_usage": "how emojis are used",
  "hashtag_style": "hashtag patterns and groups",
  "cta_patterns": "call-to-action patterns",
  "do_list": ["things the brand does well"],
  "avoid_list": ["things to avoid"],
  "sample_phrases": ["characteristic phrases"]
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt))

        cache = {
            "ig_account_id": ig_account_id or "default",
            "followers_count": profile_info.get("followers_count", 0),
            "media_count": profile_info.get("media_count", 0),
            "recent_captions": captions[:25],
            "brand_voice_analysis": json.dumps(result),
            "best_posting_times": None,
            "top_hashtags": None,
            "synced_at": datetime.utcnow().isoformat() + "Z",
        }
        await self.storage.save_profile_cache_async(cache)

        return {**result, "profile": profile_info, "ig_account_id": ig_account_id}

    async def generate_strategy(self, goals: List[str], date_range_start: str,
                                 date_range_end: str, product_focus: Optional[List[str]] = None,
                                 user_email: str = "system") -> Strategy:
        """AI generates a full content strategy with per-day content briefs anchored to real products."""
        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"

        # Fetch bestsellers and full product catalog
        bestsellers_data = []
        try:
            from bestsellers_logic import fetch_bestsellers
            bs = fetch_bestsellers(days=30)
            bestsellers_data = bs.get("bestsellers", [])[:10]
        except Exception as e:
            print(f"[SocialMediaAgent] Could not fetch bestsellers: {e}")

        product_catalog = []
        try:
            product_catalog = await self.sync_product_catalog()
            # Filter to active products only
            product_catalog = [p for p in product_catalog if p.get("status") == "active"]
        except Exception as e:
            print(f"[SocialMediaAgent] Could not sync product catalog: {e}")

        # Fallback: load products from DB if live sync returned nothing
        if not product_catalog and DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import Product
                from sqlalchemy import select
                async with get_db() as db:
                    result = await db.execute(
                        select(Product).where(Product.status == "active").order_by(Product.title)
                    )
                    rows = result.scalars().all()
                    product_catalog = [{
                        "shopify_gid": r.shopify_gid,
                        "title": r.title,
                        "handle": r.handle or "",
                        "description": (r.description or "")[:200],
                        "product_type": r.product_type or "",
                        "tags": r.tags or [],
                        "price_min": float(r.price_min) if r.price_min else None,
                        "price_max": float(r.price_max) if r.price_max else None,
                        "featured_image_url": r.featured_image_url,
                        "status": r.status or "active",
                    } for r in rows]
                    if product_catalog:
                        print(f"[SocialMediaAgent] Loaded {len(product_catalog)} products from DB")
            except Exception as e2:
                print(f"[SocialMediaAgent] Could not load products from DB: {e2}")

        # Build product context for AI
        bestseller_summary = ""
        if bestsellers_data:
            lines = []
            for i, bs in enumerate(bestsellers_data[:5]):
                lines.append(f"  {i+1}. {bs.get('product_title', 'Unknown')} — ${bs.get('total_sales', 0):.0f} revenue, {bs.get('total_qty', 0)} units")
            bestseller_summary = "TOP BESTSELLERS (last 30 days):\n" + "\n".join(lines)

        catalog_summary = ""
        if product_catalog:
            lines = []
            for p in product_catalog[:20]:
                price_str = f"${p['price_min']}" if p.get('price_min') else "N/A"
                lines.append(f"  - {p['title']} (handle: {p['handle']}, type: {p.get('product_type','')}, price: {price_str}, gid: {p['shopify_gid']})")
            catalog_summary = "PRODUCT CATALOG:\n" + "\n".join(lines)

        system_prompt = f"""You are a social media strategist for Mirai Skin, a premium K-Beauty retailer.
Create a detailed Instagram content strategy that is a CONTENT MAP — every day gets specific content briefs
anchored to REAL products from the catalog below.

Brand voice guide: {voice_guide}

{bestseller_summary}

{catalog_summary}

Return valid JSON with strategy overview AND content_briefs array."""

        user_prompt = f"""Create a content strategy for Instagram (mirrored to Facebook).

GOALS: {json.dumps(goals)}
DATE RANGE: {date_range_start} to {date_range_end}
PRODUCT FOCUS: {json.dumps(product_focus or [])}

Rules for content_briefs:
- Feature bestsellers more frequently (top 5 should appear 2-3x each across the period)
- Reels MUST have post_type "reel"
- Mix content_category across the week — never repeat the same category on consecutive days
- Each day: 1 feed post + 1-2 stories
- Every brief must reference a SPECIFIC product from the catalog by shopify_gid, title, and handle
- Distribute post times across optimal windows: 09:00, 12:00, 18:00, 20:00
- Stories at different times than feed posts

Return JSON:
{{
  "title": "Strategy name",
  "description": "Strategy summary",
  "content_mix": {{"reels": 30, "photos": 30, "carousel": 20, "product_feature": 10, "story": 10}},
  "posting_frequency": {{"posts_per_week": 7, "best_days": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"], "best_times": ["09:00", "12:00", "18:00"]}},
  "hashtag_strategy": {{
    "core_hashtags": ["#miraiskin", "#kbeauty"],
    "rotating_hashtags": [["#skincare", "#glowup"], ["#koreanbeauty", "#skincareroutine"]],
    "trending_hashtags": ["#glassskin"]
  }},
  "content_briefs": [
    {{
      "date": "YYYY-MM-DD",
      "content_category": "how-to|before-after|product-feature|lifestyle|educational|testimonial|behind-the-scenes",
      "post_type": "photo|reel|carousel|story",
      "product_to_feature": {{"shopify_gid": "gid://shopify/Product/...", "title": "Product Name", "handle": "product-handle"}},
      "visual_style": "product-only|model-with-product|flat-lay|lifestyle-scene|close-up-texture",
      "hook": "Key message or engagement angle",
      "scheduled_time": "HH:MM"
    }}
  ]
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt, max_tokens=8000))

        strategy = Strategy(
            id=str(uuid_lib.uuid4()),
            title=result.get("title", "Content Strategy"),
            description=result.get("description", ""),
            goals=goals,
            content_mix=result.get("content_mix", {}),
            posting_frequency=result.get("posting_frequency", {}),
            hashtag_strategy=result.get("hashtag_strategy", {}),
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            status="pending_review",
            created_by=user_email,
            created_at=datetime.utcnow().isoformat() + "Z",
            updated_at=datetime.utcnow().isoformat() + "Z",
            content_briefs=result.get("content_briefs"),
        )
        await self.storage.save_strategy_async(strategy)
        return strategy

    async def generate_post_content(self, post_type: str, strategy_id: Optional[str] = None,
                                     product_ids: Optional[List[str]] = None,
                                     topic_hint: Optional[str] = None,
                                     user_email: str = "system") -> Post:
        """AI generates a single post (caption + visual direction)"""
        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"

        strategy_context = ""
        strategy = None
        if strategy_id:
            strategy = await self.storage.get_strategy_async(strategy_id)
            if strategy:
                strategy_context = f"""
STRATEGY: {strategy.title}
CONTENT MIX: {json.dumps(strategy.content_mix)}
HASHTAG STRATEGY: {json.dumps(strategy.hashtag_strategy)}
"""

        campaign_slug = ""
        if strategy:
            campaign_slug = re.sub(r'[^a-z0-9]+', '-', strategy.title.lower()).strip('-')

        type_instructions = {
            "photo": "Create a visually appealing photo post. Focus on aesthetic, storytelling, and brand identity.",
            "reel": "Create an engaging Reel concept. Start with a hook in the first 3 seconds. Keep it dynamic and entertaining.",
            "carousel": "Create a carousel post (multiple slides). Each slide should have a clear purpose. Educational or step-by-step content works well.",
            "product_feature": "Create a product feature post. Highlight key benefits, ingredients, and results. Include a clear CTA to shop.",
            "story": "Create an Instagram Story. Vertical 9:16 format. Eye-catching, quick to consume. Bold visuals, minimal text overlay. Engagement-focused (polls, questions, swipe-up)."
        }

        system_prompt = f"""You are a social media content creator for Mirai Skin, a premium K-Beauty retailer.
Brand voice guide: {voice_guide}
{strategy_context}

Create Instagram content. Return valid JSON."""

        product_context = ""
        if product_ids:
            product_context = f"\nFEATURED PRODUCTS (Shopify GIDs): {json.dumps(product_ids)}"

        user_prompt = f"""Generate an Instagram {post_type} post.

POST TYPE: {post_type}
INSTRUCTIONS: {type_instructions.get(post_type, type_instructions['photo'])}
{product_context}
{f'TOPIC HINT: {topic_hint}' if topic_hint else ''}

UTM LINK FORMAT: https://miraiskin.co/products/{{handle}}?utm_source=instagram&utm_medium=organic&utm_campaign={campaign_slug or 'general'}

Return JSON:
{{
  "caption": "Full caption text including hashtags",
  "visual_direction": "Detailed description of what the image/video should look like",
  "suggested_media_type": "IMAGE or VIDEO or CAROUSEL_ALBUM",
  "hashtags": ["#tag1", "#tag2"],
  "link_url": "UTM-tagged link if applicable"
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt))

        post = Post(
            id=str(uuid_lib.uuid4()),
            strategy_id=strategy_id,
            post_type=post_type,
            caption=result.get("caption", ""),
            visual_direction=result.get("visual_direction", ""),
            status="draft",
            created_at=datetime.utcnow().isoformat() + "Z",
            updated_at=datetime.utcnow().isoformat() + "Z",
            media_type=result.get("suggested_media_type", "IMAGE"),
            product_ids=product_ids,
            link_url=result.get("link_url"),
            utm_source="instagram",
            utm_medium="organic",
            utm_campaign=campaign_slug or "general",
        )
        await self.storage.save_post_async(post)
        return post

    async def generate_batch_posts(self, strategy_id: str, user_email: str = "system") -> List[Post]:
        """Generate multiple posts for an approved strategy.
        Uses content_briefs if available, otherwise falls back to legacy generation."""
        strategy = await self.storage.get_strategy_async(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")

        # If strategy has content_briefs, use brief-driven generation
        if strategy.content_briefs and len(strategy.content_briefs) > 0:
            return await self._generate_posts_from_briefs(strategy)

        # Legacy fallback for old strategies without briefs
        return await self._generate_batch_posts_legacy(strategy)

    async def _generate_posts_from_briefs(self, strategy: Strategy) -> List[Post]:
        """Generate posts from per-day content briefs in batches of 3."""
        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"
        campaign_slug = re.sub(r'[^a-z0-9]+', '-', strategy.title.lower()).strip('-')
        briefs = strategy.content_briefs or []

        created_posts = []
        # Process briefs in batches of 3
        for i in range(0, len(briefs), 3):
            batch = briefs[i:i+3]

            briefs_text = json.dumps(batch, indent=2)

            system_prompt = f"""You are a social media content creator for Mirai Skin, a premium K-Beauty retailer.
Brand voice guide: {voice_guide}

STRATEGY: {strategy.title}
HASHTAG STRATEGY: {json.dumps(strategy.hashtag_strategy)}

Generate Instagram posts from the content briefs below. Each post must:
- Reference the specific product BY NAME in the caption
- Match the content_category angle in tone and structure
- Include the visual_style direction in the visual_direction field
- For reels: describe motion/action in visual_direction
- Include relevant hashtags from the strategy

Return valid JSON."""

            user_prompt = f"""Generate posts from these content briefs:

{briefs_text}

UTM LINK FORMAT: https://miraiskin.co/products/{{handle}}?utm_source=instagram&utm_medium=organic&utm_campaign={campaign_slug}

Return JSON:
{{
  "posts": [
    {{
      "post_type": "photo|reel|carousel|story",
      "content_category": "the category from the brief",
      "caption": "Full caption mentioning the product by name, with hashtags",
      "visual_direction": "Detailed visual description combining the brief's visual_style with the product and caption context",
      "scheduled_date": "YYYY-MM-DD from the brief",
      "scheduled_time": "HH:MM from the brief",
      "product_ids": ["shopify_gid from the brief"],
      "link_url": "UTM link to the product"
    }}
  ]
}}"""

            result = json.loads(self._call_ai(system_prompt, user_prompt, max_tokens=4000))
            posts_data = result.get("posts", [])

            for p_data in posts_data:
                scheduled_dt = None
                if p_data.get("scheduled_date"):
                    time_str = p_data.get("scheduled_time", "10:00")
                    scheduled_dt = f"{p_data['scheduled_date']}T{time_str}:00Z"

                post = Post(
                    id=str(uuid_lib.uuid4()),
                    strategy_id=strategy.id,
                    post_type=p_data.get("post_type", "photo"),
                    caption=p_data.get("caption", ""),
                    visual_direction=p_data.get("visual_direction", ""),
                    status="draft",
                    created_at=datetime.utcnow().isoformat() + "Z",
                    updated_at=datetime.utcnow().isoformat() + "Z",
                    content_category=p_data.get("content_category"),
                    media_type="VIDEO" if p_data.get("post_type") == "reel" else "IMAGE",
                    product_ids=p_data.get("product_ids"),
                    link_url=p_data.get("link_url"),
                    utm_source="instagram",
                    utm_medium="organic",
                    utm_campaign=campaign_slug,
                    scheduled_at=scheduled_dt,
                )
                await self.storage.save_post_async(post)
                created_posts.append(post)

        return created_posts

    async def _generate_batch_posts_legacy(self, strategy: Strategy) -> List[Post]:
        """Legacy single-prompt batch generation for strategies without content_briefs."""
        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"
        campaign_slug = re.sub(r'[^a-z0-9]+', '-', strategy.title.lower()).strip('-')

        system_prompt = f"""You are a social media content creator for Mirai Skin, a premium K-Beauty retailer.
Brand voice guide: {voice_guide}

STRATEGY: {strategy.title} — {strategy.description}
CONTENT MIX: {json.dumps(strategy.content_mix)}
POSTING FREQUENCY: {json.dumps(strategy.posting_frequency)}
HASHTAG STRATEGY: {json.dumps(strategy.hashtag_strategy)}
DATE RANGE: {strategy.date_range_start} to {strategy.date_range_end}

Generate a batch of posts for this strategy. Return valid JSON."""

        user_prompt = f"""Generate Instagram content for the FULL strategy period, covering EVERY DAY.

For EACH DAY in the date range, create:
- 1 FEED post (rotating types: photo ~50%, carousel ~20%, product_feature ~20%, reel ~10%)
- 1-3 STORIES (type="story", engagement-focused: polls, questions, behind-the-scenes, quick tips)

Distribute feed post times across optimal windows: 9:00, 12:00, 18:00, 20:00.
Schedule stories at different times than the feed post (e.g., 8:00, 14:00, 21:00).

UTM LINK FORMAT: https://miraiskin.co/products/{{handle}}?utm_source=instagram&utm_medium=organic&utm_campaign={campaign_slug}

Return JSON:
{{
  "posts": [
    {{
      "post_type": "photo|reel|carousel|product_feature|story",
      "caption": "Full caption with hashtags (shorter for stories)",
      "visual_direction": "Visual description for AI image generation",
      "suggested_media_type": "IMAGE|VIDEO|CAROUSEL_ALBUM",
      "scheduled_date": "YYYY-MM-DD",
      "scheduled_time": "HH:MM",
      "link_url": "UTM link if applicable"
    }}
  ]
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt))
        posts_data = result.get("posts", [])

        created_posts = []
        for p_data in posts_data:
            scheduled_dt = None
            if p_data.get("scheduled_date"):
                time_str = p_data.get("scheduled_time", "10:00")
                scheduled_dt = f"{p_data['scheduled_date']}T{time_str}:00Z"

            post = Post(
                id=str(uuid_lib.uuid4()),
                strategy_id=strategy.id,
                post_type=p_data.get("post_type", "photo"),
                caption=p_data.get("caption", ""),
                visual_direction=p_data.get("visual_direction", ""),
                status="draft",
                created_at=datetime.utcnow().isoformat() + "Z",
                updated_at=datetime.utcnow().isoformat() + "Z",
                media_type=p_data.get("suggested_media_type", "IMAGE"),
                link_url=p_data.get("link_url"),
                utm_source="instagram",
                utm_medium="organic",
                utm_campaign=campaign_slug,
                scheduled_at=scheduled_dt,
            )
            await self.storage.save_post_async(post)
            created_posts.append(post)

        return created_posts

    async def regenerate_post(self, post_id: str, hints: str) -> Post:
        """Regenerate a post with feedback hints"""
        post = await self.storage.get_post_async(post_id)
        if not post:
            raise ValueError(f"Post not found: {post_id}")

        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"

        system_prompt = f"""You are a social media content creator for Mirai Skin.
Brand voice guide: {voice_guide}
Revise this post based on feedback. Return valid JSON."""

        user_prompt = f"""Revise this Instagram post based on feedback.

ORIGINAL CAPTION: {post.caption}
ORIGINAL VISUAL DIRECTION: {post.visual_direction}
POST TYPE: {post.post_type}

FEEDBACK: {hints}

Return JSON:
{{
  "caption": "Revised caption with hashtags",
  "visual_direction": "Revised visual description",
  "link_url": "Updated UTM link if applicable"
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt))

        post.caption = result.get("caption", post.caption)
        post.visual_direction = result.get("visual_direction", post.visual_direction)
        if result.get("link_url"):
            post.link_url = result["link_url"]
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        post.status = "draft"

        await self.storage.save_post_async(post)
        return post

    async def _generate_image(self, visual_direction: str, post_type: str, engine: str = "gemini", caption: str = "") -> tuple:
        """Generate an image. engine: 'gemini' (default, no fallback), or 'dalle'.
        Returns (b64_data, thumbnail, format, engine_used)."""
        if engine == "gemini":
            result = await self._generate_image_gemini(visual_direction, post_type, caption=caption)
            if result[0]:
                print("[SocialMediaAgent] Image generated via Gemini")
                return result + ("gemini",)
            # No automatic DALL-E fallback when engine is "gemini"
            return None, None, None, None

        if engine == "dalle":
            print("[SocialMediaAgent] Using DALL-E 3")
            result = await self._generate_image_dalle(visual_direction, post_type)
            return result + ("dalle",)

        return None, None, None, None

    async def _generate_image_gemini(self, visual_direction: str, post_type: str, caption: str = "") -> tuple:
        """Generate image using Google Gemini for natural lifestyle/product photography."""
        api_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None, None, None

        aspect = "9:16" if post_type in ("story", "reel") else "1:1"

        # Extract first sentence of caption (strip hashtags) for context
        caption_context = ""
        if caption:
            clean_caption = re.sub(r'#\S+', '', caption).strip()
            first_sentence = clean_caption.split('.')[0].strip()
            if first_sentence:
                caption_context = f' The image should match this caption message: "{first_sentence}".'

        prompt = (
            f"Professional Instagram photo for a premium K-Beauty skincare brand called Mirai Skin. "
            f"{visual_direction}. "
            f"Style: natural soft lighting, clean minimal aesthetic, real editorial product photography. "
            f"The image should look like a high-end lifestyle or product photograph — "
            f"NOT an AI collage or digital art. Think Glossier or Aesop brand photography. "
            f"Aspect ratio: {aspect}."
            f"{caption_context}"
        )

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                # Gemini 2.0 Flash with native image generation
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent",
                    params={"key": api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseModalities": ["IMAGE", "TEXT"],
                        },
                    },
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            inline = part.get("inlineData", {})
                            mime = inline.get("mimeType", "")
                            if mime.startswith("image/"):
                                b64_data = inline.get("data", "")
                                if b64_data:
                                    fmt = "png" if "png" in mime else "jpeg"
                                    thumbnail = compress_to_thumbnail(b64_data, 256)
                                    return b64_data, thumbnail, fmt

                print(f"[Gemini Image] No image in response (status {resp.status_code}): {resp.text[:300]}")
        except Exception as e:
            print(f"[Gemini Image] Failed: {e}")

        return None, None, None

    async def _generate_image_dalle(self, visual_direction: str, post_type: str) -> tuple:
        """Generate an image using DALL-E 3 (fallback)."""
        size = "1024x1792" if post_type in ("story", "reel") else "1024x1024"

        enhanced_prompt = (
            f"Professional lifestyle product photography for a premium K-Beauty skincare brand. "
            f"{visual_direction}. "
            f"Style: natural soft lighting, clean minimal aesthetic, editorial product photography. "
            f"Real photo look — not digital art, not a collage."
        )

        response = self.client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size=size,
            quality="standard",
            response_format="b64_json",
            n=1,
        )
        b64_data = response.data[0].b64_json
        thumbnail = compress_to_thumbnail(b64_data, 256)
        return b64_data, thumbnail, "png"

    async def _generate_video(self, visual_direction: str, caption: str = "") -> tuple:
        """Try to generate a short video via Gemini Veo. Returns (b64_data, thumbnail, format) or (None, None, None)."""
        api_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None, None, None

        # Extract first sentence of caption for context
        caption_context = ""
        if caption:
            clean_caption = re.sub(r'#\S+', '', caption).strip()
            first_sentence = clean_caption.split('.')[0].strip()
            if first_sentence:
                caption_context = f' The video should match this message: "{first_sentence}".'

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                prompt = (
                    f"Generate a short 5-second vertical video for Instagram Reels. "
                    f"Premium K-Beauty skincare brand aesthetic. {visual_direction}. "
                    f"Smooth, cinematic, natural lighting."
                    f"{caption_context}"
                )
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent",
                    params={"key": api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseModalities": ["VIDEO", "TEXT"],
                        },
                    },
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            inline = part.get("inlineData", {})
                            mime = inline.get("mimeType", "")
                            if mime.startswith("video/"):
                                b64_data = inline.get("data", "")
                                if b64_data:
                                    return b64_data, "", "mp4"
                            elif mime.startswith("image/"):
                                # Got an image instead of video — still useful
                                b64_data = inline.get("data", "")
                                if b64_data:
                                    fmt = "png" if "png" in mime else "jpeg"
                                    thumbnail = compress_to_thumbnail(b64_data, 256)
                                    return b64_data, thumbnail, fmt

                print(f"[Gemini Video] No video in response (status {resp.status_code})")
        except Exception as e:
            print(f"[Gemini Video] Failed: {e}")

        return None, None, None

    async def generate_media_for_post(self, post_uuid: str, engine: str = "gemini") -> Post:
        """Generate AI image/video for a post using its visual_direction + caption.
        engine: 'gemini' (default, no DALL-E fallback), 'dalle' (explicit)."""
        post = await self.storage.get_post_async(post_uuid)
        if not post:
            raise ValueError(f"Post not found: {post_uuid}")
        if not post.visual_direction:
            raise ValueError("Post has no visual_direction to generate from")

        caption = post.caption or ""

        if post.post_type == "reel":
            # Try Gemini video first, fall back to image (but flag media_type)
            video_data, video_thumb, video_fmt = await self._generate_video(post.visual_direction, caption=caption)
            if video_data:
                post.media_data = video_data
                post.media_thumbnail = video_thumb
                post.media_data_format = video_fmt
                post.media_type = "VIDEO"
            else:
                # Fallback to image but set media_type=IMAGE to flag in UI
                img, thumb, fmt, _engine = await self._generate_image(post.visual_direction, post.post_type, engine, caption=caption)
                post.media_data = img
                post.media_thumbnail = thumb
                post.media_data_format = fmt
                post.media_type = "IMAGE"
        else:
            img, thumb, fmt, _engine = await self._generate_image(post.visual_direction, post.post_type, engine, caption=caption)
            post.media_data = img
            post.media_thumbnail = thumb
            post.media_data_format = fmt
            if not post.media_type:
                post.media_type = "IMAGE"

        # Set the media_url to our serve endpoint so Meta API can fetch it
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://mirai-managment-dashboard.onrender.com")
        post.media_url = f"{base_url}/api/social-media/media/{post.id}"
        post.updated_at = datetime.utcnow().isoformat() + "Z"

        await self.storage.save_post_async(post)
        return post

    def build_utm_link(self, product_url: str, campaign: str, post_uuid: Optional[str] = None) -> str:
        """Generate UTM-tagged link"""
        separator = "&" if "?" in product_url else "?"
        link = f"{product_url}{separator}utm_source=instagram&utm_medium=organic&utm_campaign={campaign}"
        if post_uuid:
            link += f"&utm_content={post_uuid[:8]}"
        return link

    async def suggest_optimal_times(self) -> Dict:
        """Data-driven scheduling recommendations"""
        insights = await self.storage.get_insights_async()
        posts = await self.storage.get_all_posts_async(status="published")

        if not posts or not insights:
            return {
                "best_days": ["Monday", "Wednesday", "Friday", "Saturday"],
                "best_times": ["10:00", "13:00", "18:00"],
                "note": "Default recommendations. More data needed for optimization."
            }

        # Analyze engagement by day/time
        day_engagement = {}
        hour_engagement = {}
        insight_map = {i.post_id: i for i in insights}

        for post in posts:
            if post.published_at and post.id in insight_map:
                try:
                    dt = datetime.fromisoformat(post.published_at.replace("Z", "+00:00"))
                    day_name = dt.strftime("%A")
                    hour = dt.hour
                    eng = insight_map[post.id].engagement

                    day_engagement.setdefault(day_name, []).append(eng)
                    hour_engagement.setdefault(hour, []).append(eng)
                except Exception:
                    pass

        best_days = sorted(day_engagement.keys(),
                          key=lambda d: sum(day_engagement[d]) / len(day_engagement[d]) if day_engagement[d] else 0,
                          reverse=True)[:4]
        best_hours = sorted(hour_engagement.keys(),
                           key=lambda h: sum(hour_engagement[h]) / len(hour_engagement[h]) if hour_engagement[h] else 0,
                           reverse=True)[:3]

        return {
            "best_days": best_days or ["Monday", "Wednesday", "Friday", "Saturday"],
            "best_times": [f"{h:02d}:00" for h in best_hours] or ["10:00", "13:00", "18:00"],
            "data_points": len(posts),
        }

    async def publish_post(self, post_id: str) -> Post:
        """Publish an approved post to Instagram and mirror to Facebook"""
        post = await self.storage.get_post_async(post_id)
        if not post:
            raise ValueError(f"Post not found: {post_id}")
        if post.status != "approved":
            raise ValueError(f"Post must be approved before publishing. Current status: {post.status}")
        if not post.media_url:
            raise ValueError("Post must have a media_url to publish")

        publisher = InstagramPublisher()
        ig_account_id = await publisher.get_ig_account_id()

        post.status = "publishing"
        await self.storage.save_post_async(post)

        try:
            # Create container based on media type / post type
            if post.post_type == "story":
                container_id = await publisher.create_story_container(ig_account_id, post.media_url)
            elif post.media_type == "VIDEO" or post.post_type == "reel":
                container_id = await publisher.create_reel_container(ig_account_id, post.media_url, post.caption)
            else:
                container_id = await publisher.create_image_container(ig_account_id, post.media_url, post.caption)

            post.ig_container_id = container_id

            # Poll for container readiness
            import asyncio
            for _ in range(30):
                status = await publisher.check_container_status(container_id)
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    raise RuntimeError("Media container creation failed")
                await asyncio.sleep(2)

            # Publish
            media_id = await publisher.publish_container(ig_account_id, container_id)
            post.ig_media_id = media_id
            post.status = "published"
            post.published_at = datetime.utcnow().isoformat() + "Z"

            # Mirror to Facebook
            fb_caption = post.caption
            if post.link_url:
                fb_caption = fb_caption.replace("utm_source=instagram", "utm_source=facebook")
            fb_post_id = await publisher.mirror_to_facebook(
                message=fb_caption,
                link=post.link_url,
                media_url=post.media_url if post.media_type == "IMAGE" else None
            )
            post.fb_post_id = fb_post_id

        except Exception as e:
            post.status = "failed"
            post.rejection_reason = f"Publishing failed: {str(e)}"
            print(f"[SocialMediaAgent] Publish failed: {e}")

        await self.storage.save_post_async(post)
        return post

    async def sync_insights(self) -> int:
        """Sync insights for all published posts"""
        posts = await self.storage.get_all_posts_async(status="published")
        synced = 0

        try:
            publisher = InstagramPublisher()
        except ValueError:
            return 0

        for post in posts:
            if not post.ig_media_id:
                continue
            try:
                metrics = await publisher.fetch_post_insights(post.ig_media_id)
                if metrics:
                    insight = PostInsight(
                        post_id=post.id,
                        ig_media_id=post.ig_media_id,
                        impressions=metrics.get("impressions", 0),
                        reach=metrics.get("reach", 0),
                        likes=metrics.get("likes", 0),
                        comments=metrics.get("comments", 0),
                        shares=metrics.get("shares", 0),
                        saves=metrics.get("saved", 0),
                        engagement=metrics.get("total_interactions", 0),
                        synced_at=datetime.utcnow().isoformat() + "Z",
                    )
                    await self.storage.save_insight_async(insight)
                    synced += 1
            except Exception as e:
                print(f"[SocialMediaAgent] Failed to sync insights for {post.id}: {e}")

        return synced

    async def sync_account_insights(self, days: int = 30) -> int:
        """Sync account-level daily metrics from Instagram Insights API."""
        try:
            publisher = InstagramPublisher()
            ig_account_id = await publisher.get_ig_account_id()
        except ValueError as e:
            print(f"[SocialMediaAgent] Cannot sync account insights: {e}")
            return 0

        end_dt = date.today()
        start_dt = end_dt - timedelta(days=days)

        # Fetch account-level insights from IG API
        daily_data = await publisher.fetch_account_insights(ig_account_id, start_dt, end_dt)

        # Also get current follower count from profile
        try:
            profile_info = await publisher.get_profile_info(ig_account_id)
            current_followers = profile_info.get("followers_count", 0)
        except Exception:
            current_followers = 0

        # Get recent media to count content published per day
        try:
            recent_media = await publisher.get_recent_media(ig_account_id, limit=50)
        except Exception:
            recent_media = []

        # Build per-day content counts from recent_media
        daily_content = {}
        for media in recent_media:
            ts = media.get("timestamp", "")[:10]
            if ts:
                daily_content.setdefault(ts, {"posts": 0, "stories": 0, "reels": 0})
                mt = media.get("media_type", "")
                if mt == "VIDEO":
                    daily_content[ts]["reels"] += 1
                else:
                    daily_content[ts]["posts"] += 1

        # Also count from our own published posts
        our_posts = await self.storage.get_all_posts_async(status="published")
        for p in our_posts:
            if p.published_at:
                pub_date = p.published_at[:10]
                daily_content.setdefault(pub_date, {"posts": 0, "stories": 0, "reels": 0})
                if p.post_type == "story":
                    daily_content[pub_date]["stories"] += 1
                elif p.post_type == "reel":
                    daily_content[pub_date]["reels"] += 1
                else:
                    daily_content[pub_date]["posts"] += 1

        synced = 0
        for day_data in daily_data:
            day_date = day_data.get("date", "")
            content = daily_content.get(day_date, {})
            snapshot = {
                "date": day_date,
                "ig_account_id": ig_account_id,
                "impressions": day_data.get("impressions", 0),
                "reach": day_data.get("reach", 0),
                "profile_views": day_data.get("profile_views", 0),
                "website_clicks": day_data.get("website_clicks", 0),
                "follower_count": day_data.get("follower_count", current_followers),
                "posts_published": content.get("posts", 0),
                "stories_published": content.get("stories", 0),
                "reels_published": content.get("reels", 0),
            }
            await self.storage.save_account_snapshot_async(snapshot)
            synced += 1

        return synced

    async def get_analytics(self, period_days: int = 7, end_date_str: Optional[str] = None) -> Dict:
        """Get analytics with period comparison.

        Returns current period metrics, previous period metrics, deltas,
        daily data for charts, top posts, and post-type breakdowns.
        """
        end_dt = date.fromisoformat(end_date_str) if end_date_str else date.today()
        start_dt = end_dt - timedelta(days=period_days - 1)
        prev_end_dt = start_dt - timedelta(days=1)
        prev_start_dt = prev_end_dt - timedelta(days=period_days - 1)

        # Get snapshots for both periods
        current_snapshots = await self.storage.get_account_snapshots_async(
            start_dt.isoformat(), end_dt.isoformat()
        )
        prev_snapshots = await self.storage.get_account_snapshots_async(
            prev_start_dt.isoformat(), prev_end_dt.isoformat()
        )

        def _sum_metric(snapshots, key):
            return sum(s.get(key, 0) for s in snapshots)

        def _avg_metric(snapshots, key):
            vals = [s.get(key, 0) for s in snapshots if s.get(key, 0) > 0]
            return round(sum(vals) / len(vals), 1) if vals else 0

        def _delta(current, previous):
            if previous == 0:
                return 100 if current > 0 else 0
            return round((current - previous) / previous * 100, 1)

        # Aggregate current period
        c_impressions = _sum_metric(current_snapshots, "impressions")
        c_reach = _sum_metric(current_snapshots, "reach")
        c_profile_views = _sum_metric(current_snapshots, "profile_views")
        c_website_clicks = _sum_metric(current_snapshots, "website_clicks")
        c_followers = current_snapshots[-1].get("follower_count", 0) if current_snapshots else 0
        c_follows = _sum_metric(current_snapshots, "follows")
        c_likes = _sum_metric(current_snapshots, "total_likes")
        c_comments = _sum_metric(current_snapshots, "total_comments")
        c_saves = _sum_metric(current_snapshots, "total_saves")
        c_shares = _sum_metric(current_snapshots, "total_shares")
        c_engagement = c_likes + c_comments + c_saves + c_shares
        c_posts = _sum_metric(current_snapshots, "posts_published")
        c_stories = _sum_metric(current_snapshots, "stories_published")
        c_reels = _sum_metric(current_snapshots, "reels_published")

        # Aggregate previous period
        p_impressions = _sum_metric(prev_snapshots, "impressions")
        p_reach = _sum_metric(prev_snapshots, "reach")
        p_profile_views = _sum_metric(prev_snapshots, "profile_views")
        p_website_clicks = _sum_metric(prev_snapshots, "website_clicks")
        p_followers = prev_snapshots[-1].get("follower_count", 0) if prev_snapshots else 0
        p_engagement = (
            _sum_metric(prev_snapshots, "total_likes") +
            _sum_metric(prev_snapshots, "total_comments") +
            _sum_metric(prev_snapshots, "total_saves") +
            _sum_metric(prev_snapshots, "total_shares")
        )

        # Engagement rate
        c_eng_rate = round(c_engagement / c_reach * 100, 2) if c_reach else 0
        p_eng_rate = round(p_engagement / p_reach * 100, 2) if p_reach else 0

        # Get post-level insights for top posts in current period
        insights = await self.storage.get_insights_async()
        published_posts = await self.storage.get_all_posts_async(status="published")

        # Build top posts list with metrics
        insight_map = {i.post_id: i for i in insights}
        top_posts = []
        for post in published_posts:
            if post.id in insight_map:
                ins = insight_map[post.id]
                top_posts.append({
                    "id": post.id,
                    "post_type": post.post_type,
                    "caption": (post.caption or "")[:100],
                    "media_thumbnail": post.media_thumbnail,
                    "published_at": post.published_at,
                    "impressions": ins.impressions,
                    "reach": ins.reach,
                    "likes": ins.likes,
                    "comments": ins.comments,
                    "saves": ins.saves,
                    "shares": ins.shares,
                    "engagement": ins.engagement,
                })
        top_posts.sort(key=lambda x: x.get("engagement", 0), reverse=True)

        # Post type breakdown from our published posts
        type_breakdown = {}
        for post in published_posts:
            pt = post.post_type or "photo"
            if pt not in type_breakdown:
                type_breakdown[pt] = {"count": 0, "impressions": 0, "reach": 0, "engagement": 0}
            type_breakdown[pt]["count"] += 1
            if post.id in insight_map:
                ins = insight_map[post.id]
                type_breakdown[pt]["impressions"] += ins.impressions
                type_breakdown[pt]["reach"] += ins.reach
                type_breakdown[pt]["engagement"] += ins.engagement

        # Add avg per post for each type
        for pt, data in type_breakdown.items():
            cnt = data["count"]
            data["avg_impressions"] = round(data["impressions"] / cnt) if cnt else 0
            data["avg_reach"] = round(data["reach"] / cnt) if cnt else 0
            data["avg_engagement"] = round(data["engagement"] / cnt) if cnt else 0

        # Also try to get live data from IG API for real-time profile stats
        live_profile = {}
        try:
            publisher = InstagramPublisher()
            ig_account_id = await publisher.get_ig_account_id()
            live_profile = await publisher.get_profile_info(ig_account_id)
        except Exception:
            pass

        return {
            "period": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "days": period_days,
                "prev_start": prev_start_dt.isoformat(),
                "prev_end": prev_end_dt.isoformat(),
            },
            "current": {
                "impressions": c_impressions,
                "reach": c_reach,
                "profile_views": c_profile_views,
                "website_clicks": c_website_clicks,
                "follower_count": c_followers,
                "net_followers": c_follows,
                "engagement": c_engagement,
                "engagement_rate": c_eng_rate,
                "likes": c_likes,
                "comments": c_comments,
                "saves": c_saves,
                "shares": c_shares,
                "posts_published": c_posts,
                "stories_published": c_stories,
                "reels_published": c_reels,
            },
            "previous": {
                "impressions": p_impressions,
                "reach": p_reach,
                "profile_views": p_profile_views,
                "website_clicks": p_website_clicks,
                "follower_count": p_followers,
                "engagement": p_engagement,
                "engagement_rate": p_eng_rate,
            },
            "deltas": {
                "impressions": _delta(c_impressions, p_impressions),
                "reach": _delta(c_reach, p_reach),
                "profile_views": _delta(c_profile_views, p_profile_views),
                "website_clicks": _delta(c_website_clicks, p_website_clicks),
                "follower_count": _delta(c_followers, p_followers),
                "engagement": _delta(c_engagement, p_engagement),
                "engagement_rate": round(c_eng_rate - p_eng_rate, 2),
            },
            "daily": current_snapshots,
            "previous_daily": prev_snapshots,
            "top_posts": top_posts[:10],
            "type_breakdown": type_breakdown,
            "live_profile": {
                "username": live_profile.get("username", ""),
                "followers_count": live_profile.get("followers_count", c_followers),
                "media_count": live_profile.get("media_count", 0),
                "biography": live_profile.get("biography", ""),
            },
        }


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_social_media_agent(api_key: Optional[str] = None) -> SocialMediaAgent:
    return SocialMediaAgent(api_key)

def create_social_media_storage() -> SocialMediaStorage:
    return SocialMediaStorage()

def create_instagram_publisher() -> InstagramPublisher:
    return InstagramPublisher()

async def create_instagram_publisher_from_db() -> InstagramPublisher:
    """Create an InstagramPublisher using credentials stored in the database.
    Falls back to environment variables if no DB connection exists."""
    storage = SocialMediaStorage()
    connection = await storage.get_active_connection_async("instagram")
    if connection:
        return InstagramPublisher(
            access_token=connection["access_token"],
            page_id=connection.get("page_id"),
            ig_account_id=connection.get("ig_account_id"),
        )
    # Fallback to env vars
    return InstagramPublisher()
