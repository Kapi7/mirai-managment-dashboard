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
from datetime import datetime, date
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
                existing.approved_at = datetime.fromisoformat(strategy.approved_at.replace("Z", "+00:00")) if strategy.approved_at else None
            else:
                db_strategy = SocialMediaStrategy(
                    uuid=strategy.id,
                    title=strategy.title,
                    description=strategy.description,
                    goals=strategy.goals,
                    content_mix=strategy.content_mix,
                    posting_frequency=strategy.posting_frequency,
                    hashtag_strategy=strategy.hashtag_strategy,
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
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except Exception:
                    return None

            if existing:
                existing.post_type = post.post_type
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
                if strategy_fk:
                    existing.strategy_id = strategy_fk
            else:
                db_post = SocialMediaPost(
                    uuid=post.id,
                    strategy_id=strategy_fk,
                    post_type=post.post_type,
                    caption=post.caption,
                    visual_direction=post.visual_direction,
                    media_url=post.media_url,
                    media_type=post.media_type,
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

            return self._db_post_to_dataclass(p, strategy_uuid)

    def _db_post_to_dataclass(self, p, strategy_uuid=None) -> Post:
        return Post(
            id=p.uuid,
            strategy_id=strategy_uuid,
            post_type=p.post_type or "",
            caption=p.caption or "",
            visual_direction=p.visual_direction or "",
            status=p.status or "draft",
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


# ============================================================
# INSTAGRAM PUBLISHER — Meta Content Publishing API
# ============================================================

class InstagramPublisher:
    def __init__(self, access_token: Optional[str] = None, page_id: Optional[str] = None):
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN")
        self.page_id = page_id or os.getenv("META_PAGE_ID")
        if not self.access_token:
            raise ValueError("META_ACCESS_TOKEN not configured")

    async def _request(self, method: str, url: str, **kwargs) -> Dict:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def get_ig_account_id(self) -> str:
        cached = os.getenv("META_IG_ACCOUNT_ID")
        if cached:
            return cached
        data = await self._request("GET", f"{META_GRAPH_URL}/{self.page_id}",
                                    params={"fields": "instagram_business_account", "access_token": self.access_token})
        ig = data.get("instagram_business_account", {}).get("id")
        if not ig:
            raise ValueError("No Instagram Business Account linked to this Page")
        return ig

    async def get_profile_info(self, ig_account_id: str) -> Dict:
        data = await self._request("GET", f"{META_GRAPH_URL}/{ig_account_id}",
                                    params={"fields": "followers_count,media_count,username,biography",
                                            "access_token": self.access_token})
        return data

    async def get_recent_media(self, ig_account_id: str, limit: int = 25) -> List[Dict]:
        data = await self._request("GET", f"{META_GRAPH_URL}/{ig_account_id}/media",
                                    params={"fields": "caption,timestamp,media_type,like_count,comments_count,permalink",
                                            "limit": limit, "access_token": self.access_token})
        return data.get("data", [])

    async def create_image_container(self, ig_account_id: str, image_url: str, caption: str) -> str:
        data = await self._request("POST", f"{META_GRAPH_URL}/{ig_account_id}/media",
                                    data={"image_url": image_url, "caption": caption,
                                          "access_token": self.access_token})
        return data["id"]

    async def create_reel_container(self, ig_account_id: str, video_url: str, caption: str) -> str:
        data = await self._request("POST", f"{META_GRAPH_URL}/{ig_account_id}/media",
                                    data={"video_url": video_url, "caption": caption,
                                          "media_type": "REELS", "access_token": self.access_token})
        return data["id"]

    async def create_carousel_container(self, ig_account_id: str, children_ids: List[str], caption: str) -> str:
        data = await self._request("POST", f"{META_GRAPH_URL}/{ig_account_id}/media",
                                    data={"media_type": "CAROUSEL", "caption": caption,
                                          "children": ",".join(children_ids),
                                          "access_token": self.access_token})
        return data["id"]

    async def check_container_status(self, container_id: str) -> str:
        data = await self._request("GET", f"{META_GRAPH_URL}/{container_id}",
                                    params={"fields": "status_code", "access_token": self.access_token})
        return data.get("status_code", "IN_PROGRESS")

    async def publish_container(self, ig_account_id: str, container_id: str) -> str:
        data = await self._request("POST", f"{META_GRAPH_URL}/{ig_account_id}/media_publish",
                                    data={"creation_id": container_id, "access_token": self.access_token})
        return data["id"]

    async def mirror_to_facebook(self, message: str, link: Optional[str] = None,
                                  media_url: Optional[str] = None) -> Optional[str]:
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

    async def fetch_post_insights(self, ig_media_id: str) -> Dict:
        try:
            data = await self._request("GET", f"{META_GRAPH_URL}/{ig_media_id}/insights",
                                        params={"metric": "impressions,reach,saved,shares,likes,comments,total_interactions",
                                                "access_token": self.access_token})
            metrics = {}
            for item in data.get("data", []):
                metrics[item["name"]] = item["values"][0]["value"] if item.get("values") else 0
            return metrics
        except Exception as e:
            print(f"[InstagramPublisher] Failed to fetch insights for {ig_media_id}: {e}")
            return {}


# ============================================================
# SOCIAL MEDIA AI AGENT
# ============================================================

class SocialMediaAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        self.client = _get_openai_client(api_key=self.api_key)
        self.storage = SocialMediaStorage()

    def _call_ai(self, system_prompt: str, user_prompt: str, json_mode: bool = True) -> str:
        kwargs = {"model": "gpt-4o", "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], "temperature": 0.7, "max_tokens": 4000}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

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
        """AI generates a full content strategy"""
        cache = await self.storage.get_profile_cache_async()
        voice_guide = cache.get("brand_voice_analysis", "{}") if cache else "{}"

        system_prompt = f"""You are a social media strategist for Mirai Skin, a premium K-Beauty retailer.
Create a detailed Instagram content strategy. The brand voice guide is:
{voice_guide}

Return valid JSON with the strategy details."""

        user_prompt = f"""Create a content strategy for Instagram (mirrored to Facebook).

GOALS: {json.dumps(goals)}
DATE RANGE: {date_range_start} to {date_range_end}
PRODUCT FOCUS: {json.dumps(product_focus or [])}

Return JSON:
{{
  "title": "Strategy name",
  "description": "Strategy summary",
  "content_mix": {{"reels": 40, "photos": 40, "product_features": 20}},
  "posting_frequency": {{"posts_per_week": 4, "best_days": ["Monday", "Wednesday", "Friday", "Saturday"], "best_times": ["10:00", "18:00"]}},
  "hashtag_strategy": {{
    "core_hashtags": ["#miraiskin", "#kbeauty"],
    "rotating_hashtags": [["#skincare", "#glowup"], ["#koreanbeauty", "#skincareroutine"]],
    "trending_hashtags": ["#glassskin"]
  }},
  "weekly_themes": [
    {{"week": 1, "theme": "Theme name", "posts": [
      {{"day": "Monday", "type": "reel", "topic": "Topic description"}},
      {{"day": "Wednesday", "type": "photo", "topic": "Topic description"}}
    ]}}
  ]
}}"""

        result = json.loads(self._call_ai(system_prompt, user_prompt))

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
            "product_feature": "Create a product feature post. Highlight key benefits, ingredients, and results. Include a clear CTA to shop."
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
        """Generate multiple posts for an approved strategy"""
        strategy = await self.storage.get_strategy_async(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")

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

        user_prompt = f"""Generate Instagram posts for the full strategy period.
Create posts following the content mix and posting frequency.
UTM LINK FORMAT: https://miraiskin.co/products/{{handle}}?utm_source=instagram&utm_medium=organic&utm_campaign={campaign_slug}

Return JSON:
{{
  "posts": [
    {{
      "post_type": "photo|reel|carousel|product_feature",
      "caption": "Full caption with hashtags",
      "visual_direction": "Visual description",
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
                strategy_id=strategy_id,
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
            # Create container based on media type
            if post.media_type == "VIDEO" or post.post_type == "reel":
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


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_social_media_agent(api_key: Optional[str] = None) -> SocialMediaAgent:
    return SocialMediaAgent(api_key)

def create_social_media_storage() -> SocialMediaStorage:
    return SocialMediaStorage()

def create_instagram_publisher() -> InstagramPublisher:
    return InstagramPublisher()
