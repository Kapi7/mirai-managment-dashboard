"""
CMO Agent — Chief Marketing Officer.

The top-level agent in the Mirai marketing hierarchy.
Responsibilities:
- Weekly content-calendar planning across all channels
- Budget allocation between organic and paid
- Cross-agent task orchestration (Content, Social, Acquisition)
- Monthly performance reviews and strategy adjustments
- KPI tracking and reporting
"""

import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from .base_agent import BaseAgent
from .content_calendar import ContentCalendar
from .content_asset_store import ContentAssetStore

# ---------------------------------------------------------------------------
# Brand constants
# ---------------------------------------------------------------------------

MIRAI_BRAND_VOICE = (
    "Brand: Mirai Skin — Premium K-Beauty skincare retailer. "
    "Tone: Sophisticated, educational, warm. Think trusted friend who knows "
    "skincare science. "
    "Content pillars: education, social_proof, product_showcase, lifestyle, "
    "promotion."
)

CONTENT_PILLARS = {
    "education":        0.30,
    "social_proof":     0.25,
    "product_showcase": 0.25,
    "lifestyle":        0.20,
}

# Optimal posting schedule (hour:minute) per format
FEED_POST_TIMES = ["09:00", "12:00", "18:00", "20:00"]
STORY_TIMES     = ["08:00", "14:00", "21:00"]
TIKTOK_TIMES    = ["11:00", "17:00", "20:00"]

# Channels and daily quotas
DAILY_SLOTS = {
    "instagram_feed":  1,
    "instagram_story": 2,   # 1-2 stories per day
    "tiktok":          1,
}


class CMOAgent(BaseAgent):
    """Chief Marketing Officer — orchestrates the entire marketing pipeline."""

    agent_name = "cmo"

    def __init__(self):
        super().__init__()
        self.calendar = ContentCalendar()
        self.asset_store = ContentAssetStore()

        # Register task handlers
        self.register_handler("create_weekly_plan", self._handle_weekly_plan)
        self.register_handler("monthly_review", self._handle_monthly_review)
        self.register_handler("allocate_budget", self._handle_allocate_budget)
        self.register_handler("adjust_strategy", self._handle_adjust_strategy)
        self.register_handler("generate_kpi_report", self._handle_kpi_report)

    def get_supported_tasks(self) -> List[str]:
        return list(self._task_handlers.keys())

    # ------------------------------------------------------------------
    # Context gathering helpers
    # ------------------------------------------------------------------

    def _get_shopify_products(self) -> List[Dict[str, Any]]:
        """Lazy-import Shopify client and fetch product catalog."""
        try:
            import sys, os
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            from shopify_client import fetch_product_catalog
            return fetch_product_catalog()
        except Exception as e:
            print(f"[cmo] Shopify product fetch failed: {e}")
            return []

    def _get_shopify_orders(self, days: int = 30) -> List[Dict[str, Any]]:
        """Lazy-import Shopify client and fetch recent orders."""
        try:
            import sys, os
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            from shopify_client import fetch_orders_created_between

            end = datetime.utcnow()
            start = end - timedelta(days=days)
            return fetch_orders_created_between(
                start.strftime("%Y-%m-%dT00:00:00Z"),
                end.strftime("%Y-%m-%dT23:59:59Z"),
            )
        except Exception as e:
            print(f"[cmo] Shopify orders fetch failed: {e}")
            return []

    def _derive_bestsellers(
        self, orders: List[Dict[str, Any]], top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """Aggregate order line-items to find top-selling products."""
        product_sales: Dict[str, Dict[str, Any]] = {}
        for order in orders:
            line_items = (order.get("lineItems") or {}).get("nodes") or []
            for item in line_items:
                variant = item.get("variant") or {}
                product = variant.get("product") or {}
                pid = product.get("id", "unknown")
                qty = item.get("quantity", 0)
                revenue_raw = (
                    (item.get("originalTotalSet") or {})
                    .get("shopMoney", {})
                    .get("amount", "0")
                )
                revenue = float(revenue_raw)

                if pid not in product_sales:
                    product_sales[pid] = {
                        "product_id": pid,
                        "title": product.get("title", ""),
                        "units_sold": 0,
                        "revenue": 0.0,
                    }
                product_sales[pid]["units_sold"] += qty
                product_sales[pid]["revenue"] += revenue

        ranked = sorted(
            product_sales.values(), key=lambda x: x["revenue"], reverse=True
        )
        return ranked[:top_n]

    async def _gather_performance_context(
        self, days: int = 7
    ) -> Dict[str, Any]:
        """
        Collect all the context the AI planner needs:
        social metrics, ad metrics, content gaps, product data.
        """
        # Products and bestsellers
        products = self._get_shopify_products()
        orders = self._get_shopify_orders(days=30)
        bestsellers = self._derive_bestsellers(orders, top_n=10)

        # Existing calendar slots for the upcoming week
        week_start = datetime.utcnow().date()
        week_start_str = week_start.isoformat()
        existing_slots = await self.calendar.get_week_plan(week_start_str)

        # Content assets available but unused
        unused_assets = await self.asset_store.list_assets(
            status="ready", used_in_organic=False, limit=20
        )

        # Brands represented in catalog
        brands = list(
            {p.get("vendor", "Mirai Skin") for p in products if p.get("vendor")}
        )

        return {
            "product_catalog_size": len(products),
            "brands": brands,
            "bestsellers": bestsellers,
            "orders_last_30d": len(orders),
            "existing_week_slots": len(existing_slots),
            "unused_assets_count": len(unused_assets),
            "products_sample": [
                {
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "vendor": p.get("vendor"),
                    "productType": p.get("productType"),
                    "tags": p.get("tags", [])[:5],
                }
                for p in products[:20]
            ],
        }

    # ------------------------------------------------------------------
    # 1.  create_weekly_plan
    # ------------------------------------------------------------------

    async def _handle_weekly_plan(self, params: dict) -> dict:
        """
        Build the full weekly content calendar:
        - 1 IG feed post / day, 1-2 IG stories / day, 1 TikTok / day
        - Refresh ad creatives
        - Balanced content pillars & brand rotation
        - Create downstream tasks for Content, Social, Acquisition agents
        """
        week_offset = params.get("week_offset", 0)  # 0 = this week
        base_date = datetime.utcnow().date() + timedelta(weeks=week_offset)
        # Align to Monday
        monday = base_date - timedelta(days=base_date.weekday())

        context = await self._gather_performance_context()

        # ---------- AI strategic planning ----------
        ai_plan = await self._generate_ai_plan(monday, context)

        # Log the planning decision BEFORE creating tasks
        decision_uuid = await self.log_decision(
            decision_type="weekly_plan",
            context={
                "week_start": monday.isoformat(),
                "product_catalog_size": context["product_catalog_size"],
                "bestsellers_count": len(context.get("bestsellers", [])),
            },
            decision={
                "ai_plan_summary": (ai_plan or {}).get("summary", ""),
                "week_start": monday.isoformat(),
            },
            reasoning=(
                f"Planning {monday.isoformat()} week: IG feed, stories, TikTok daily. "
                f"Balanced across pillars ({', '.join(CONTENT_PILLARS.keys())}). "
                f"Brand rotation enforced to avoid repetition."
            ),
            confidence=0.85,
            requires_approval=True,
        )

        # ---------- Fill calendar slots ----------
        created_slots = []
        content_tasks: List[str] = []
        pillar_pool = self._build_pillar_pool(7)
        used_brands_today: Optional[str] = None

        products_by_brand = self._group_products_by_brand(
            context.get("products_sample", [])
        )
        brand_list = list(products_by_brand.keys()) or ["Mirai Skin"]

        for day_offset in range(7):
            slot_date = (monday + timedelta(days=day_offset)).isoformat()
            day_pillar_index = day_offset  # rotate pillars

            # Pick brand ensuring no consecutive repeats
            brand = self._pick_brand(brand_list, used_brands_today)
            used_brands_today = brand

            # Pick a product from that brand
            brand_products = products_by_brand.get(brand, [])
            product = random.choice(brand_products) if brand_products else {}
            product_id = product.get("id", "")

            # -- Instagram Feed (1 per day) --
            pillar = pillar_pool[day_pillar_index % len(pillar_pool)]
            post_type = self._post_type_for_pillar(pillar)
            feed_time = FEED_POST_TIMES[day_offset % len(FEED_POST_TIMES)]
            brief = self._extract_brief_for_day(ai_plan, day_offset, "instagram_feed")

            slot = await self.calendar.create_slot(
                slot_date=slot_date,
                time_slot=feed_time,
                channel="instagram",
                content_pillar=pillar,
                content_category="feed",
                post_type=post_type,
                brief=brief,
                product_id=product_id,
                created_by_agent=self.agent_name,
            )
            created_slots.append(slot.uuid)

            # Create Content Agent task for this slot
            content_task_id = await self.create_task(
                target_agent="content",
                task_type="create_asset",
                params={
                    "calendar_slot_uuid": slot.uuid,
                    "channel": "instagram",
                    "content_category": "feed",
                    "content_pillar": pillar,
                    "post_type": post_type,
                    "product_id": product_id,
                    "brand": brand,
                    "brief": brief,
                    "brand_voice": MIRAI_BRAND_VOICE,
                },
                priority="normal",
                requires_approval=True,
                decision_uuid=decision_uuid,
            )
            content_tasks.append(content_task_id)

            # Dependent: Social Agent publishes after asset is ready
            await self.create_task(
                target_agent="social",
                task_type="publish_post",
                params={
                    "calendar_slot_uuid": slot.uuid,
                    "channel": "instagram",
                    "scheduled_time": f"{slot_date}T{feed_time}:00Z",
                },
                priority="normal",
                depends_on=[content_task_id],
                requires_approval=True,
                decision_uuid=decision_uuid,
            )

            # -- Instagram Stories (1-2 per day) --
            num_stories = 1 if day_offset % 3 == 0 else 2
            for s_idx in range(num_stories):
                story_pillar = pillar_pool[
                    (day_pillar_index + s_idx + 1) % len(pillar_pool)
                ]
                story_time = STORY_TIMES[s_idx % len(STORY_TIMES)]
                story_brief = self._extract_brief_for_day(
                    ai_plan, day_offset, f"instagram_story_{s_idx}"
                )

                story_slot = await self.calendar.create_slot(
                    slot_date=slot_date,
                    time_slot=story_time,
                    channel="instagram",
                    content_pillar=story_pillar,
                    content_category="story",
                    post_type="story",
                    brief=story_brief,
                    product_id=product_id,
                    created_by_agent=self.agent_name,
                )
                created_slots.append(story_slot.uuid)

                story_content_id = await self.create_task(
                    target_agent="content",
                    task_type="create_asset",
                    params={
                        "calendar_slot_uuid": story_slot.uuid,
                        "channel": "instagram",
                        "content_category": "story",
                        "content_pillar": story_pillar,
                        "post_type": "story",
                        "product_id": product_id,
                        "brand": brand,
                        "brief": story_brief,
                        "brand_voice": MIRAI_BRAND_VOICE,
                    },
                    priority="normal",
                    requires_approval=True,
                    decision_uuid=decision_uuid,
                )
                content_tasks.append(story_content_id)

                await self.create_task(
                    target_agent="social",
                    task_type="publish_story",
                    params={
                        "calendar_slot_uuid": story_slot.uuid,
                        "channel": "instagram",
                        "scheduled_time": f"{slot_date}T{story_time}:00Z",
                    },
                    priority="normal",
                    depends_on=[story_content_id],
                    requires_approval=True,
                    decision_uuid=decision_uuid,
                )

            # -- TikTok (1 per day) --
            tiktok_pillar = pillar_pool[
                (day_pillar_index + 3) % len(pillar_pool)
            ]
            tiktok_time = TIKTOK_TIMES[day_offset % len(TIKTOK_TIMES)]
            tiktok_brief = self._extract_brief_for_day(
                ai_plan, day_offset, "tiktok"
            )

            tiktok_slot = await self.calendar.create_slot(
                slot_date=slot_date,
                time_slot=tiktok_time,
                channel="tiktok",
                content_pillar=tiktok_pillar,
                content_category="feed",
                post_type="reel",
                brief=tiktok_brief,
                product_id=product_id,
                created_by_agent=self.agent_name,
            )
            created_slots.append(tiktok_slot.uuid)

            tiktok_content_id = await self.create_task(
                target_agent="content",
                task_type="create_asset",
                params={
                    "calendar_slot_uuid": tiktok_slot.uuid,
                    "channel": "tiktok",
                    "content_category": "feed",
                    "content_pillar": tiktok_pillar,
                    "post_type": "reel",
                    "product_id": product_id,
                    "brand": brand,
                    "brief": tiktok_brief,
                    "brand_voice": MIRAI_BRAND_VOICE,
                },
                priority="normal",
                requires_approval=True,
                decision_uuid=decision_uuid,
            )
            content_tasks.append(tiktok_content_id)

            await self.create_task(
                target_agent="social",
                task_type="publish_post",
                params={
                    "calendar_slot_uuid": tiktok_slot.uuid,
                    "channel": "tiktok",
                    "scheduled_time": f"{slot_date}T{tiktok_time}:00Z",
                },
                priority="normal",
                depends_on=[tiktok_content_id],
                requires_approval=True,
                decision_uuid=decision_uuid,
            )

        # -- Ad creative refresh (runs once after all content is queued) --
        ad_task_id = await self.create_task(
            target_agent="acquisition",
            task_type="refresh_ad_creatives",
            params={
                "week_start": monday.isoformat(),
                "bestsellers": context.get("bestsellers", [])[:5],
                "brand_voice": MIRAI_BRAND_VOICE,
            },
            priority="normal",
            depends_on=content_tasks[:3],  # wait for first few assets
            requires_approval=True,
            decision_uuid=decision_uuid,
        )

        return {
            "week_start": monday.isoformat(),
            "slots_created": len(created_slots),
            "slot_uuids": created_slots,
            "content_tasks_created": len(content_tasks),
            "ad_refresh_task": ad_task_id,
            "ai_plan_summary": (ai_plan or {}).get("summary", ""),
        }

    # ------------------------------------------------------------------
    # 2.  monthly_review
    # ------------------------------------------------------------------

    async def _handle_monthly_review(self, params: dict) -> dict:
        """Comprehensive monthly performance review across all channels."""
        month = params.get("month")  # YYYY-MM
        if not month:
            now = datetime.utcnow()
            first = now.replace(day=1)
            prev_month = first - timedelta(days=1)
            month = prev_month.strftime("%Y-%m")

        year, m = month.split("-")
        month_start = f"{month}-01"
        # Calculate month end
        if int(m) == 12:
            month_end = f"{int(year) + 1}-01-01"
        else:
            month_end = f"{year}-{int(m) + 1:02d}-01"

        orders = self._get_shopify_orders(days=60)
        # Filter to month
        month_orders = [
            o for o in orders
            if (o.get("createdAt") or "")[:7] == month
        ]

        # Revenue calculation
        total_revenue = 0.0
        for order in month_orders:
            for item in (order.get("lineItems") or {}).get("nodes") or []:
                amount = (
                    (item.get("originalTotalSet") or {})
                    .get("shopMoney", {})
                    .get("amount", "0")
                )
                total_revenue += float(amount)

        # Calendar slot stats
        slots = await self.calendar.get_week_plan(month_start)
        published = [s for s in slots if s.status == "published"]
        planned = [s for s in slots if s.status == "planned"]

        # Asset performance aggregates
        assets = await self.asset_store.list_assets(limit=100)
        total_impressions = sum(a.total_impressions for a in assets)
        total_engagement = sum(a.total_engagement for a in assets)
        avg_engagement_rate = (
            (total_engagement / total_impressions * 100)
            if total_impressions > 0
            else 0.0
        )

        # AI-generated analysis
        review_prompt = f"""
You are the CMO of Mirai Skin, a premium K-Beauty retailer.
Review the following monthly performance data for {month} and provide
a concise executive summary with 3 key wins, 3 areas for improvement,
and 3 strategic recommendations for next month.

Data:
- Orders: {len(month_orders)}
- Revenue: ${total_revenue:,.2f}
- Content slots published: {len(published)}
- Content slots still planned: {len(planned)}
- Total impressions (tracked assets): {total_impressions:,}
- Average engagement rate: {avg_engagement_rate:.2f}%
- Total content assets produced: {len(assets)}

Respond in JSON with keys: summary, wins (list), improvements (list),
recommendations (list).
"""
        ai_review = "{}"
        try:
            ai_review = await self.call_ai_text(
                prompt=review_prompt,
                system_prompt=MIRAI_BRAND_VOICE,
                model="gemini",
                temperature=0.5,
                json_mode=True,
            )
        except Exception as e:
            print(f"[cmo] AI monthly review failed: {e}")

        parsed_review = {}
        try:
            parsed_review = json.loads(ai_review)
        except json.JSONDecodeError:
            parsed_review = {"summary": ai_review}

        await self.log_decision(
            decision_type="monthly_review",
            context={"month": month, "revenue": total_revenue},
            decision=parsed_review,
            reasoning=f"Monthly review for {month} covering orders, content, engagement.",
            confidence=0.75,
            requires_approval=False,
        )

        return {
            "month": month,
            "orders": len(month_orders),
            "revenue": total_revenue,
            "slots_published": len(published),
            "slots_planned": len(planned),
            "total_impressions": total_impressions,
            "avg_engagement_rate": round(avg_engagement_rate, 2),
            "total_assets": len(assets),
            "ai_review": parsed_review,
        }

    # ------------------------------------------------------------------
    # 3.  allocate_budget
    # ------------------------------------------------------------------

    async def _handle_allocate_budget(self, params: dict) -> dict:
        """
        Distribute monthly budget between organic and paid channels.

        Rules:
          ROAS > 2.0  -> increase paid allocation (up to 70%)
          ROAS < 1.5  -> shift to organic (paid drops to 30%)
          Default     -> 50/50
        """
        monthly_budget = params.get("monthly_budget", 5000.0)
        current_roas = params.get("current_roas", 0.0)

        if current_roas > 2.0:
            paid_pct = min(0.70, 0.50 + (current_roas - 2.0) * 0.05)
        elif current_roas < 1.5:
            paid_pct = max(0.30, 0.50 - (1.5 - current_roas) * 0.10)
        else:
            paid_pct = 0.50

        organic_pct = 1.0 - paid_pct
        paid_budget = round(monthly_budget * paid_pct, 2)
        organic_budget = round(monthly_budget * organic_pct, 2)

        reasoning = (
            f"ROAS={current_roas:.2f}. "
            f"{'High ROAS — shifting more to paid.' if current_roas > 2.0 else ''}"
            f"{'Low ROAS — shifting toward organic.' if current_roas < 1.5 else ''}"
            f"{'ROAS in healthy range — balanced split.' if 1.5 <= current_roas <= 2.0 else ''}"
        )

        allocation = {
            "monthly_budget": monthly_budget,
            "paid_pct": round(paid_pct * 100, 1),
            "organic_pct": round(organic_pct * 100, 1),
            "paid_budget": paid_budget,
            "organic_budget": organic_budget,
            "current_roas": current_roas,
        }

        decision_uuid = await self.log_decision(
            decision_type="budget_allocation",
            context={"monthly_budget": monthly_budget, "current_roas": current_roas},
            decision=allocation,
            reasoning=reasoning,
            confidence=0.80,
            requires_approval=True,
        )

        return allocation

    # ------------------------------------------------------------------
    # 4.  adjust_strategy
    # ------------------------------------------------------------------

    async def _handle_adjust_strategy(self, params: dict) -> dict:
        """
        Pivot marketing strategy based on performance signals.
        Examines engagement, ROAS, content gaps, and seasonality.
        """
        trigger = params.get("trigger", "manual")
        performance_data = params.get("performance_data", {})

        strategy_prompt = f"""
You are the CMO of Mirai Skin, a premium K-Beauty skincare retailer.

Current performance signals:
{json.dumps(performance_data, indent=2, default=str)}

Trigger for strategy adjustment: {trigger}

{MIRAI_BRAND_VOICE}

Based on these signals, recommend specific strategy adjustments.
Consider:
1. Which content pillars to emphasize or de-emphasize
2. Whether to shift budget between paid and organic
3. Whether to change posting frequency or timing
4. Any seasonal K-Beauty trends to leverage (e.g. summer hydration,
   winter barrier repair, spring brightening, fall anti-aging)
5. Product spotlight recommendations based on performance

Respond in JSON with keys:
- pillar_adjustments (dict of pillar -> weight change, e.g. +0.05 or -0.05)
- budget_shift (string: "increase_paid", "increase_organic", or "maintain")
- frequency_changes (dict of channel -> new daily count)
- seasonal_hooks (list of string)
- product_spotlights (list of product suggestions)
- rationale (string)
"""
        ai_strategy = "{}"
        try:
            ai_strategy = await self.call_ai_text(
                prompt=strategy_prompt,
                system_prompt=MIRAI_BRAND_VOICE,
                model="gemini",
                temperature=0.6,
                json_mode=True,
            )
        except Exception as e:
            print(f"[cmo] AI strategy adjustment failed: {e}")

        parsed = {}
        try:
            parsed = json.loads(ai_strategy)
        except json.JSONDecodeError:
            parsed = {"rationale": ai_strategy}

        decision_uuid = await self.log_decision(
            decision_type="strategy_adjustment",
            context={"trigger": trigger, "performance_data": performance_data},
            decision=parsed,
            reasoning=parsed.get("rationale", "AI-driven strategy pivot."),
            confidence=0.70,
            requires_approval=True,
        )

        return {
            "trigger": trigger,
            "adjustments": parsed,
        }

    # ------------------------------------------------------------------
    # 5.  generate_kpi_report
    # ------------------------------------------------------------------

    async def _handle_kpi_report(self, params: dict) -> dict:
        """
        Generate a KPI tracking report.
        Metrics: follower growth, engagement rate, ROAS, revenue attribution.
        """
        period_days = params.get("period_days", 30)
        goals = params.get("goals", {})

        orders = self._get_shopify_orders(days=period_days)
        bestsellers = self._derive_bestsellers(orders, top_n=5)

        total_revenue = 0.0
        for order in orders:
            for item in (order.get("lineItems") or {}).get("nodes") or []:
                amount = (
                    (item.get("originalTotalSet") or {})
                    .get("shopMoney", {})
                    .get("amount", "0")
                )
                total_revenue += float(amount)

        assets = await self.asset_store.list_assets(limit=200)
        total_impressions = sum(a.total_impressions for a in assets)
        total_engagement = sum(a.total_engagement for a in assets)
        total_clicks = sum(a.total_clicks for a in assets)
        avg_engagement_rate = (
            (total_engagement / total_impressions * 100)
            if total_impressions > 0
            else 0.0
        )

        # Calculate paid-channel ROAS from assets used in ads
        ad_assets = [a for a in assets if a.used_in_paid]
        ad_revenue = sum(a.ad_roas for a in ad_assets)  # aggregate ROAS metric
        avg_roas = (
            (ad_revenue / len(ad_assets)) if ad_assets else 0.0
        )

        # Goal tracking
        goal_tracking = {}
        default_goals = {
            "monthly_revenue": 50000,
            "engagement_rate": 3.5,
            "roas_target": 2.0,
            "content_pieces_per_week": 28,
        }
        effective_goals = {**default_goals, **goals}

        goal_tracking["revenue"] = {
            "target": effective_goals["monthly_revenue"],
            "actual": round(total_revenue, 2),
            "pct": round(
                total_revenue / effective_goals["monthly_revenue"] * 100, 1
            )
            if effective_goals["monthly_revenue"] > 0
            else 0,
        }
        goal_tracking["engagement_rate"] = {
            "target": effective_goals["engagement_rate"],
            "actual": round(avg_engagement_rate, 2),
            "on_track": avg_engagement_rate >= effective_goals["engagement_rate"],
        }
        goal_tracking["roas"] = {
            "target": effective_goals["roas_target"],
            "actual": round(avg_roas, 2),
            "on_track": avg_roas >= effective_goals["roas_target"],
        }

        report = {
            "period_days": period_days,
            "orders": len(orders),
            "revenue": round(total_revenue, 2),
            "bestsellers": bestsellers,
            "total_impressions": total_impressions,
            "total_engagement": total_engagement,
            "total_clicks": total_clicks,
            "avg_engagement_rate": round(avg_engagement_rate, 2),
            "avg_roas": round(avg_roas, 2),
            "total_assets_produced": len(assets),
            "assets_used_in_ads": len(ad_assets),
            "goal_tracking": goal_tracking,
        }

        await self.log_decision(
            decision_type="kpi_report",
            context={"period_days": period_days},
            decision=report,
            reasoning=f"KPI report for the past {period_days} days.",
            confidence=0.90,
            requires_approval=False,
        )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_ai_plan(
        self, monday: Any, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ask AI (GPT-4o preferred for strategic reasoning) to produce a
        7-day content plan with specific briefs per slot.
        """
        bestseller_names = [
            b.get("title", "") for b in context.get("bestsellers", [])
        ]
        brands = context.get("brands", ["Mirai Skin"])

        planning_prompt = f"""
You are the Chief Marketing Officer of Mirai Skin, a curated premium
K-Beauty skincare retailer. Plan the content calendar for the week
starting {monday.isoformat()}.

{MIRAI_BRAND_VOICE}

CONTEXT:
- Product catalog: {context.get('product_catalog_size', 0)} products across
  brands: {', '.join(brands[:8])}
- Current bestsellers: {', '.join(bestseller_names[:5]) or 'N/A'}
- Orders last 30 days: {context.get('orders_last_30d', 0)}
- Unused content assets available: {context.get('unused_assets_count', 0)}

CHANNEL REQUIREMENTS:
- Instagram Feed: 1 post/day — high-quality photo, carousel, or reel.
  Optimal times: {', '.join(FEED_POST_TIMES)}
- Instagram Stories: 1-2/day — quick polls, tips, product teasers.
  Optimal times: {', '.join(STORY_TIMES)}
- TikTok: 1 video/day — trending formats, skincare routines, ingredient
  deep-dives. Optimal times: {', '.join(TIKTOK_TIMES)}

CONTENT PILLAR MIX (per week):
- Education (30%): Ingredient spotlights, routine guides, K-Beauty science
  (e.g. double cleansing, 7-skin method, snail mucin benefits, centella
  asiatica vs niacinamide)
- Social Proof (25%): UGC reposts, customer reviews, before/after,
  dermatologist quotes
- Product Showcase (25%): New arrivals, bestseller features, texture shots,
  "shelfie" styling, ingredient close-ups
- Lifestyle (20%): Morning/evening routines, self-care rituals, Korean
  beauty culture, seasonal skincare transitions

RULES:
1. Never feature the same brand on consecutive days.
2. Each day should have a clear theme that ties IG feed + stories + TikTok.
3. Leverage trending K-Beauty ingredients: snail mucin, centella, rice water,
   propolis, mugwort, green tea, hyaluronic acid, retinol alternatives.
4. Include at least one educational carousel per week explaining an
   ingredient or routine.
5. Include at least one social-proof post per week (review, UGC, or
   testimonial).
6. TikTok content should be optimized for discovery — use trending audio
   hooks and formats.

Respond in JSON with this structure:
{{
  "summary": "One-line theme for the week",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "theme": "Day theme",
      "instagram_feed": {{
        "pillar": "education|social_proof|product_showcase|lifestyle",
        "post_type": "photo|carousel|reel",
        "brief": "Detailed creative brief (2-3 sentences)",
        "product_focus": "product name or empty",
        "hashtag_themes": ["hashtag1", "hashtag2"]
      }},
      "instagram_stories": [
        {{
          "pillar": "...",
          "brief": "Story brief",
          "format": "poll|quiz|tip|product_teaser|behind_the_scenes"
        }}
      ],
      "tiktok": {{
        "pillar": "...",
        "brief": "TikTok video brief with hook suggestion",
        "format": "routine|ingredient_spotlight|review|trend|tutorial",
        "trending_hook": "Suggested opening hook"
      }}
    }}
  ]
}}
"""
        try:
            raw = await self.call_ai_text(
                prompt=planning_prompt,
                system_prompt=(
                    "You are a K-Beauty marketing strategist. Respond ONLY "
                    "with valid JSON. Be specific with product names and "
                    "creative directions."
                ),
                model="gemini",
                temperature=0.7,
                json_mode=True,
            )
            return json.loads(raw)
        except Exception as e:
            print(f"[cmo] AI plan generation failed: {e}")
            return {"summary": "Fallback plan — manual briefs needed", "days": []}

    def _build_pillar_pool(self, num_days: int) -> List[str]:
        """
        Create a shuffled list of content pillars respecting the target
        distribution across the given number of days.
        """
        pool: List[str] = []
        for pillar, weight in CONTENT_PILLARS.items():
            count = max(1, round(weight * num_days * 3))  # ~3 slots per day
            pool.extend([pillar] * count)
        random.shuffle(pool)
        return pool

    def _pick_brand(
        self, brand_list: List[str], last_brand: Optional[str]
    ) -> str:
        """Pick a brand that differs from yesterday's."""
        if len(brand_list) <= 1:
            return brand_list[0] if brand_list else "Mirai Skin"
        candidates = [b for b in brand_list if b != last_brand]
        return random.choice(candidates) if candidates else brand_list[0]

    def _group_products_by_brand(
        self, products: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group product sample by vendor/brand."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for p in products:
            brand = p.get("vendor") or "Mirai Skin"
            grouped.setdefault(brand, []).append(p)
        return grouped

    def _post_type_for_pillar(self, pillar: str) -> str:
        """Map pillar to a default post type."""
        mapping = {
            "education": "carousel",
            "social_proof": "photo",
            "product_showcase": "photo",
            "lifestyle": "reel",
        }
        return mapping.get(pillar, "photo")

    def _extract_brief_for_day(
        self,
        ai_plan: Dict[str, Any],
        day_offset: int,
        slot_type: str,
    ) -> str:
        """
        Pull the AI-generated brief for a specific day and slot type.
        Falls back to a generic brief if the AI plan is missing data.
        """
        days = ai_plan.get("days", [])
        if day_offset >= len(days):
            return f"Create engaging {slot_type} content aligned with brand voice."

        day = days[day_offset]

        if slot_type == "instagram_feed":
            feed = day.get("instagram_feed", {})
            return feed.get("brief", f"IG feed post — {day.get('theme', 'brand story')}")

        if slot_type.startswith("instagram_story"):
            idx = 0
            if "_" in slot_type:
                parts = slot_type.rsplit("_", 1)
                try:
                    idx = int(parts[-1])
                except ValueError:
                    idx = 0
            stories = day.get("instagram_stories", [])
            if idx < len(stories):
                return stories[idx].get("brief", "Engage followers with a quick story.")
            return "Engage followers with a quick skincare tip or poll."

        if slot_type == "tiktok":
            tt = day.get("tiktok", {})
            brief = tt.get("brief", "")
            hook = tt.get("trending_hook", "")
            return f"{brief} Hook: {hook}" if hook else (brief or "Short-form K-Beauty video.")

        return f"Create {slot_type} content for Mirai Skin."
