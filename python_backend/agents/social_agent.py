"""
Social Network Agent — Manages publishing to Instagram, Facebook, and TikTok.

Agent 1 in the CMO hierarchy. Responsibilities:
- Publish content assets to social platforms (Instagram, Facebook, TikTok)
- Schedule weekly publishing from the content calendar
- Sync engagement insights from platform APIs
- Analyze optimal posting times from historical data
- Generate structured performance reports for the CMO agent

Uses the shared ContentAssetStore for reading assets and ContentCalendar
for reading/updating the publishing schedule.
"""

import os
import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import asdict

from .base_agent import BaseAgent

# ---------------------------------------------------------------------------
# Lazy imports — heavy services loaded on first use only
# ---------------------------------------------------------------------------

_instagram_publisher = None
_tiktok_publisher = None
_social_storage = None
_asset_store = None
_calendar = None


def _get_instagram_publisher():
    global _instagram_publisher
    if _instagram_publisher is None:
        from social_media_service import InstagramPublisher
        _instagram_publisher = InstagramPublisher()
    return _instagram_publisher


def _get_tiktok_publisher():
    global _tiktok_publisher
    if _tiktok_publisher is None:
        from .tiktok_publisher import TikTokPublisher
        _tiktok_publisher = TikTokPublisher()
    return _tiktok_publisher


def _get_social_storage():
    global _social_storage
    if _social_storage is None:
        from social_media_service import SocialMediaStorage
        _social_storage = SocialMediaStorage()
    return _social_storage


def _get_asset_store():
    global _asset_store
    if _asset_store is None:
        from .content_asset_store import ContentAssetStore
        _asset_store = ContentAssetStore()
    return _asset_store


def _get_calendar():
    global _calendar
    if _calendar is None:
        from .content_calendar import ContentCalendar
        _calendar = ContentCalendar()
    return _calendar


# ---------------------------------------------------------------------------
# Platform caption limits and formatting rules
# ---------------------------------------------------------------------------

PLATFORM_RULES = {
    "instagram": {
        "max_caption_length": 2200,
        "hashtag_placement": "end",
        "style": "full_caption_with_hashtags",
    },
    "facebook": {
        "max_caption_length": 1500,
        "hashtag_placement": "none",
        "style": "conversational_no_hashtags",
    },
    "tiktok": {
        "max_caption_length": 150,
        "hashtag_placement": "inline",
        "style": "short_punchy_trending_hashtags",
    },
}


# ---------------------------------------------------------------------------
# Social Network Agent
# ---------------------------------------------------------------------------

class SocialNetworkAgent(BaseAgent):
    """
    Publishes content to Instagram, Facebook, and TikTok. Tracks engagement
    and feeds performance data back to the CMO agent for strategic decisions.
    """

    agent_name: str = "social"

    def __init__(self):
        super().__init__()

        # Register task handlers
        self.register_handler("publish_from_asset", self.publish_from_asset)
        self.register_handler("schedule_week", self.schedule_week)
        self.register_handler("sync_insights", self.sync_insights)
        self.register_handler("analyze_best_times", self.analyze_best_times)
        self.register_handler("generate_performance_report", self.generate_performance_report)

    def get_supported_tasks(self) -> List[str]:
        return list(self._task_handlers.keys())

    # ------------------------------------------------------------------
    # Task 1: publish_from_asset
    # ------------------------------------------------------------------

    async def publish_from_asset(self, params: dict) -> dict:
        """
        Publish a content asset to its target platform.

        Required params:
            asset_uuid: str — UUID of the content asset to publish
            calendar_slot_uuid: str — UUID of the calendar slot this fulfills

        Optional params:
            platform_override: str — force a specific platform (instagram/facebook/tiktok)
        """
        asset_uuid = params.get("asset_uuid")
        slot_uuid = params.get("calendar_slot_uuid")
        if not asset_uuid or not slot_uuid:
            return {"error": "asset_uuid and calendar_slot_uuid are required"}

        store = _get_asset_store()
        calendar = _get_calendar()

        asset = await store.get_asset(asset_uuid)
        if not asset:
            return {"error": f"Asset {asset_uuid} not found"}

        slot = await calendar.get_slot(slot_uuid)
        if not slot:
            return {"error": f"Calendar slot {slot_uuid} not found"}

        platform = params.get("platform_override") or slot.channel or "instagram"
        caption = await self._format_caption_for_platform(asset, platform)

        await self.log_decision(
            decision_type="publish",
            context={
                "asset_uuid": asset_uuid,
                "slot_uuid": slot_uuid,
                "platform": platform,
                "content_pillar": asset.content_pillar,
                "content_category": asset.content_category,
            },
            decision={"action": "publish", "platform": platform},
            reasoning=f"Publishing asset '{asset.title}' to {platform} per calendar schedule.",
            confidence=0.9,
            requires_approval=False,
        )

        result = {}

        if platform == "instagram":
            result = await self._publish_to_instagram(asset, caption)
        elif platform == "facebook":
            result = await self._publish_to_facebook(asset, caption)
        elif platform == "tiktok":
            result = await self._publish_to_tiktok(asset, caption)
        else:
            return {"error": f"Unsupported platform: {platform}"}

        # Update calendar slot and asset usage tracking on success
        if result.get("published"):
            post_uuid = result.get("post_id", "")
            await calendar.mark_published(slot_uuid, post_uuid=post_uuid)
            await store.mark_used(asset_uuid, "organic", post_uuid)

        return result

    async def _publish_to_instagram(self, asset, caption: str) -> dict:
        """Publish to Instagram via the Graph API."""
        try:
            publisher = _get_instagram_publisher()
            ig_id = await publisher.get_ig_account_id()
            image_url = asset.primary_image_url

            if not image_url:
                return {"error": "Asset has no primary_image_url for Instagram publishing"}

            post_type = self._detect_post_type(asset)

            if post_type == "carousel" and asset.carousel_images:
                # Publish carousel: create child containers first
                children_ids = []
                for img in asset.carousel_images:
                    img_url = img.get("url") or img.get("image_url")
                    if img_url:
                        child_id = await publisher.create_image_container(ig_id, img_url, "")
                        children_ids.append(child_id)

                if not children_ids:
                    return {"error": "No valid carousel image URLs found"}

                container_id = await publisher.create_carousel_container(
                    ig_id, children_ids, caption
                )
            elif post_type == "reel" and asset.video_url:
                container_id = await publisher.create_reel_container(
                    ig_id, asset.video_url, caption
                )
            else:
                container_id = await publisher.create_image_container(
                    ig_id, image_url, caption
                )

            # Wait for container to finish processing
            await self._wait_for_container(publisher, container_id)

            media_id = await publisher.publish_container(ig_id, container_id)

            # Mirror to Facebook as well
            fb_post_id = await publisher.mirror_to_facebook(
                message=caption,
                media_url=image_url,
            )

            return {
                "published": True,
                "platform": "instagram",
                "post_id": media_id,
                "container_id": container_id,
                "fb_mirror_id": fb_post_id,
                "post_type": post_type,
            }
        except Exception as e:
            return {"published": False, "platform": "instagram", "error": str(e)}

    async def _publish_to_facebook(self, asset, caption: str) -> dict:
        """Publish directly to Facebook (without Instagram)."""
        try:
            publisher = _get_instagram_publisher()
            fb_post_id = await publisher.mirror_to_facebook(
                message=caption,
                media_url=asset.primary_image_url,
                link=asset.cta_text if asset.cta_text.startswith("http") else None,
            )
            if not fb_post_id:
                return {"published": False, "platform": "facebook",
                        "error": "Facebook publish returned no post ID (may require EAA token)"}
            return {
                "published": True,
                "platform": "facebook",
                "post_id": fb_post_id,
            }
        except Exception as e:
            return {"published": False, "platform": "facebook", "error": str(e)}

    async def _publish_to_tiktok(self, asset, caption: str) -> dict:
        """Publish a video to TikTok."""
        try:
            publisher = _get_tiktok_publisher()
            if not asset.video_url:
                return {"error": "Asset has no video_url for TikTok publishing"}

            result = await publisher.publish_video(
                video_url=asset.video_url,
                caption=caption,
            )
            return {
                "published": True,
                "platform": "tiktok",
                "post_id": result.get("publish_id", ""),
            }
        except Exception as e:
            return {"published": False, "platform": "tiktok", "error": str(e)}

    async def _wait_for_container(self, publisher, container_id: str, max_retries: int = 10):
        """Poll the container status until it is ready or fails."""
        for _ in range(max_retries):
            status = await publisher.check_container_status(container_id)
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(f"Container {container_id} processing failed")
            await asyncio.sleep(3)
        raise TimeoutError(f"Container {container_id} did not finish within {max_retries * 3}s")

    def _detect_post_type(self, asset) -> str:
        """Determine the appropriate post type from asset content."""
        if asset.video_url or asset.video_data:
            return "reel"
        if asset.carousel_images and len(asset.carousel_images) > 1:
            return "carousel"
        return "photo"

    # ------------------------------------------------------------------
    # Task 2: schedule_week
    # ------------------------------------------------------------------

    async def schedule_week(self, params: dict) -> dict:
        """
        Read calendar slots with status 'asset_ready' and create publish
        tasks for each one, scheduled at the slot's designated time.

        Optional params:
            week_start: str (YYYY-MM-DD) — defaults to next Monday
            channels: list[str] — filter to specific channels
        """
        calendar = _get_calendar()

        week_start = params.get("week_start")
        if not week_start:
            today = date.today()
            days_ahead = 7 - today.weekday()  # Next Monday
            if days_ahead == 7:
                days_ahead = 0
            week_start = (today + timedelta(days=days_ahead)).isoformat()

        channels_filter = params.get("channels")
        week_slots = await calendar.get_week_plan(week_start)

        # Keep only asset_ready slots
        ready_slots = [
            s for s in week_slots
            if s.status == "asset_ready" and s.asset_uuid
        ]

        if channels_filter:
            ready_slots = [s for s in ready_slots if s.channel in channels_filter]

        if not ready_slots:
            return {
                "scheduled": 0,
                "week_start": week_start,
                "message": "No asset_ready slots found for the week.",
            }

        task_ids = []
        for slot in ready_slots:
            # Compute the scheduled datetime from slot date + time_slot
            scheduled_for = None
            if slot.time_slot:
                try:
                    scheduled_for = datetime.strptime(
                        f"{slot.date} {slot.time_slot}", "%Y-%m-%d %H:%M"
                    )
                except ValueError:
                    pass

            task_id = await self.create_task(
                target_agent="social",
                task_type="publish_from_asset",
                params={
                    "asset_uuid": slot.asset_uuid,
                    "calendar_slot_uuid": slot.uuid,
                },
                priority="normal",
                scheduled_for=scheduled_for,
            )
            task_ids.append(task_id)

        await self.log_decision(
            decision_type="schedule_week",
            context={"week_start": week_start, "total_slots": len(week_slots)},
            decision={"scheduled_count": len(task_ids), "task_ids": task_ids},
            reasoning=(
                f"Scheduled {len(task_ids)} publish tasks for week of {week_start}. "
                f"{len(week_slots)} total slots found, {len(ready_slots)} were asset_ready."
            ),
            confidence=0.85,
            requires_approval=False,
        )

        return {
            "scheduled": len(task_ids),
            "week_start": week_start,
            "task_ids": task_ids,
            "slots": [
                {"uuid": s.uuid, "date": s.date, "channel": s.channel, "asset_uuid": s.asset_uuid}
                for s in ready_slots
            ],
        }

    # ------------------------------------------------------------------
    # Task 3: sync_insights
    # ------------------------------------------------------------------

    async def sync_insights(self, params: dict) -> dict:
        """
        Fetch the latest engagement insights from Instagram and persist them.

        Optional params:
            days_back: int — how many days of insights to fetch (default 7)
        """
        days_back = params.get("days_back", 7)
        storage = _get_social_storage()

        try:
            publisher = _get_instagram_publisher()
            ig_id = await publisher.get_ig_account_id()
        except Exception as e:
            return {"error": f"Could not initialize Instagram publisher: {str(e)}"}

        until_date = date.today()
        since_date = until_date - timedelta(days=days_back)

        # Fetch account-level daily insights
        account_insights = await publisher.fetch_account_insights(ig_id, since_date, until_date)

        # Fetch recent media with per-post insights
        recent_media = await publisher.fetch_recent_media_detailed(ig_id, limit=50)

        # Persist per-post insights to storage
        from social_media_service import PostInsight

        synced_count = 0
        for media in recent_media:
            ig_media_id = media.get("id", "")
            insights = media.get("insights", {})
            if not ig_media_id:
                continue

            # Try to match to an existing post by ig_media_id
            posts = await storage.get_all_posts_async(status="published")
            matched_post = next(
                (p for p in posts if p.ig_media_id == ig_media_id), None
            )
            post_id = matched_post.id if matched_post else ig_media_id

            insight = PostInsight(
                post_id=post_id,
                ig_media_id=ig_media_id,
                impressions=insights.get("impressions", 0),
                reach=insights.get("reach", 0),
                engagement=insights.get("total_interactions", 0),
                likes=insights.get("likes", media.get("like_count", 0)),
                comments=insights.get("comments", media.get("comments_count", 0)),
                shares=insights.get("shares", 0),
                saves=insights.get("saved", 0),
                synced_at=datetime.utcnow().isoformat(),
            )
            await storage.save_insight_async(insight)
            synced_count += 1

        return {
            "synced_post_insights": synced_count,
            "account_insight_days": len(account_insights),
            "date_range": {"since": since_date.isoformat(), "until": until_date.isoformat()},
            "account_insights_summary": account_insights[:3] if account_insights else [],
        }

    # ------------------------------------------------------------------
    # Task 4: analyze_best_times
    # ------------------------------------------------------------------

    async def analyze_best_times(self, params: dict) -> dict:
        """
        Analyze historical engagement data to find optimal posting times
        for each platform.

        Optional params:
            lookback_days: int — how far back to analyze (default 30)
        """
        lookback_days = params.get("lookback_days", 30)
        storage = _get_social_storage()

        # Gather published posts with timestamps
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

        posts = await storage.get_all_posts_async(
            status="published", start_date=start_date, end_date=end_date
        )
        all_insights = await storage.get_insights_async()

        # Build a lookup for insights by post_id
        insight_map = {i.post_id: i for i in all_insights}

        # Group engagement by hour and day-of-week
        hourly_engagement: Dict[int, List[float]] = {h: [] for h in range(24)}
        daily_engagement: Dict[int, List[float]] = {d: [] for d in range(7)}

        for post in posts:
            if not post.published_at and not post.scheduled_at:
                continue
            ts_str = post.published_at or post.scheduled_at
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            insight = insight_map.get(post.id)
            engagement_rate = 0.0
            if insight and insight.reach > 0:
                engagement_rate = insight.engagement / insight.reach
            elif insight:
                engagement_rate = float(insight.engagement)

            hourly_engagement[ts.hour].append(engagement_rate)
            daily_engagement[ts.weekday()].append(engagement_rate)

        def _avg(values: list) -> float:
            return round(sum(values) / len(values), 4) if values else 0.0

        hourly_avg = {h: _avg(v) for h, v in hourly_engagement.items() if v}
        daily_avg = {d: _avg(v) for d, v in daily_engagement.items() if v}

        # Find top 3 hours and top 3 days
        top_hours = sorted(hourly_avg.items(), key=lambda x: x[1], reverse=True)[:3]
        top_days = sorted(daily_avg.items(), key=lambda x: x[1], reverse=True)[:3]

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        result = {
            "analysis_period_days": lookback_days,
            "posts_analyzed": len(posts),
            "best_hours": [{"hour": h, "avg_engagement_rate": r} for h, r in top_hours],
            "best_days": [
                {"day": day_names[d], "day_index": d, "avg_engagement_rate": r}
                for d, r in top_days
            ],
            "hourly_breakdown": {str(h): _avg(v) for h, v in hourly_engagement.items()},
            "daily_breakdown": {day_names[d]: _avg(v) for d, v in daily_engagement.items()},
        }

        await self.log_decision(
            decision_type="best_times_analysis",
            context={"lookback_days": lookback_days, "posts_analyzed": len(posts)},
            decision=result,
            reasoning=(
                f"Analyzed {len(posts)} published posts over {lookback_days} days. "
                f"Top posting hours: {[h for h, _ in top_hours]}. "
                f"Top posting days: {[day_names[d] for d, _ in top_days]}."
            ),
            confidence=0.7 if len(posts) >= 20 else 0.4,
            requires_approval=False,
        )

        return result

    # ------------------------------------------------------------------
    # Task 5: generate_performance_report
    # ------------------------------------------------------------------

    async def generate_performance_report(self, params: dict) -> dict:
        """
        Aggregate engagement metrics by content_category, content_pillar,
        and post_type. Returns a structured report the CMO agent can use
        for strategic planning.

        Optional params:
            days: int — reporting window (default 30)
        """
        days = params.get("days", 30)
        storage = _get_social_storage()

        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        posts = await storage.get_all_posts_async(
            status="published", start_date=start_date, end_date=end_date
        )
        all_insights = await storage.get_insights_async()
        insight_map = {i.post_id: i for i in all_insights}

        # Aggregation buckets
        by_category: Dict[str, Dict] = {}
        by_pillar: Dict[str, Dict] = {}
        by_post_type: Dict[str, Dict] = {}
        totals = _empty_totals()

        for post in posts:
            insight = insight_map.get(post.id)
            if not insight:
                continue

            metrics = {
                "impressions": insight.impressions,
                "reach": insight.reach,
                "engagement": insight.engagement,
                "likes": insight.likes,
                "comments": insight.comments,
                "shares": insight.shares,
                "saves": insight.saves,
            }

            _accumulate(totals, metrics)

            cat = post.content_category or "uncategorized"
            if cat not in by_category:
                by_category[cat] = _empty_totals()
            _accumulate(by_category[cat], metrics)

            # Content pillar comes from the asset, but we track it via caption match
            # or fallback to the calendar. For published posts, use strategy_id context.
            pillar = getattr(post, "content_pillar", None) or "unknown"
            if pillar == "unknown" and post.strategy_id:
                pillar = post.strategy_id[:8]  # Fallback label
            if pillar not in by_pillar:
                by_pillar[pillar] = _empty_totals()
            _accumulate(by_pillar[pillar], metrics)

            pt = post.post_type or "unknown"
            if pt not in by_post_type:
                by_post_type[pt] = _empty_totals()
            _accumulate(by_post_type[pt], metrics)

        # Compute engagement rates
        _add_rates(totals)
        for bucket in [by_category, by_pillar, by_post_type]:
            for key in bucket:
                _add_rates(bucket[key])

        # Rank categories by engagement rate
        ranked_categories = sorted(
            by_category.items(),
            key=lambda x: x[1].get("engagement_rate", 0),
            reverse=True,
        )

        report = {
            "period_days": days,
            "total_posts": len(posts),
            "totals": totals,
            "by_content_category": dict(ranked_categories),
            "by_content_pillar": by_pillar,
            "by_post_type": by_post_type,
            "top_category": ranked_categories[0][0] if ranked_categories else None,
            "generated_at": datetime.utcnow().isoformat(),
        }

        await self.log_decision(
            decision_type="performance_report",
            context={"period_days": days, "total_posts": len(posts)},
            decision={"top_category": report["top_category"], "total_engagement": totals["engagement"]},
            reasoning=(
                f"Performance report for {days} days covering {len(posts)} posts. "
                f"Top category: {report['top_category']}. "
                f"Overall engagement rate: {totals.get('engagement_rate', 0):.2%}."
            ),
            confidence=0.8,
            requires_approval=False,
        )

        return report

    # ------------------------------------------------------------------
    # Caption formatting (platform-specific)
    # ------------------------------------------------------------------

    async def _format_caption_for_platform(self, asset, platform: str) -> str:
        """
        Format the asset's text content for the target platform.

        Instagram: full caption with hashtags appended at the end.
        Facebook:  shorter, conversational, no hashtags.
        TikTok:    short punchy caption with trending hashtags inline.
        """
        rules = PLATFORM_RULES.get(platform, PLATFORM_RULES["instagram"])

        # Use pre-formatted platform-specific captions if available
        if platform == "instagram" and asset.instagram_caption:
            caption = asset.instagram_caption
        elif platform == "tiktok" and asset.tiktok_caption:
            caption = asset.tiktok_caption
        elif platform == "facebook" and asset.body_copy:
            caption = asset.body_copy
        else:
            # Fall back to AI-generated platform formatting
            caption = await self._ai_format_caption(asset, platform, rules)

        # Enforce platform length limits
        max_len = rules["max_caption_length"]
        if len(caption) > max_len:
            caption = caption[:max_len - 3].rsplit(" ", 1)[0] + "..."

        return caption

    async def _ai_format_caption(self, asset, platform: str, rules: dict) -> str:
        """Use AI to reformat asset body_copy for a specific platform."""
        source_text = asset.body_copy or asset.headline or asset.title
        hashtags = " ".join(f"#{t}" for t in (asset.hashtags or []))

        system_prompt = (
            "You are a social media copywriter for Mirai Skin, a premium K-Beauty brand. "
            "Reformat the provided text for the target platform. Follow the rules exactly."
        )

        if platform == "instagram":
            user_prompt = (
                f"Reformat this for Instagram (max 2200 chars). Keep the full message, "
                f"add hashtags at the end separated by a line break. "
                f"Core hashtags to always include: #MiraiSkin #KBeauty #KoreanSkincare\n\n"
                f"Source text: {source_text}\n"
                f"Additional hashtags: {hashtags}"
            )
        elif platform == "facebook":
            user_prompt = (
                f"Reformat this for Facebook (max 1500 chars). Make it conversational and warm. "
                f"Do NOT include any hashtags. Add a soft call-to-action at the end.\n\n"
                f"Source text: {source_text}"
            )
        elif platform == "tiktok":
            user_prompt = (
                f"Reformat this for TikTok (max 150 chars total). Make it short and punchy. "
                f"Include 2-3 trending hashtags inline. Must grab attention immediately.\n\n"
                f"Source text: {source_text}\n"
                f"Available hashtags: {hashtags}"
            )
        else:
            return source_text

        try:
            formatted = await self.call_ai_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.6,
            )
            # AI might return JSON-wrapped text; extract plain text
            try:
                parsed = json.loads(formatted)
                if isinstance(parsed, dict):
                    formatted = parsed.get("caption") or parsed.get("text") or formatted
            except (json.JSONDecodeError, TypeError):
                pass
            return formatted.strip()
        except Exception as e:
            print(f"[SocialNetworkAgent] AI caption formatting failed: {e}")
            # Graceful fallback: return source text with basic formatting
            if platform == "instagram":
                return f"{source_text}\n\n{hashtags}\n#MiraiSkin #KBeauty #KoreanSkincare"
            elif platform == "tiktok":
                truncated = source_text[:120] if len(source_text) > 120 else source_text
                return f"{truncated} #MiraiSkin #KBeauty"
            return source_text


# ---------------------------------------------------------------------------
# Report aggregation helpers
# ---------------------------------------------------------------------------

def _empty_totals() -> dict:
    return {
        "post_count": 0,
        "impressions": 0,
        "reach": 0,
        "engagement": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
    }


def _accumulate(totals: dict, metrics: dict):
    totals["post_count"] += 1
    for key in ("impressions", "reach", "engagement", "likes", "comments", "shares", "saves"):
        totals[key] += metrics.get(key, 0)


def _add_rates(totals: dict):
    """Compute derived rates from raw totals."""
    if totals["reach"] > 0:
        totals["engagement_rate"] = round(totals["engagement"] / totals["reach"], 4)
    else:
        totals["engagement_rate"] = 0.0

    if totals["impressions"] > 0:
        totals["save_rate"] = round(totals["saves"] / totals["impressions"], 4)
        totals["share_rate"] = round(totals["shares"] / totals["impressions"], 4)
    else:
        totals["save_rate"] = 0.0
        totals["share_rate"] = 0.0
