"""
Acquisition Agent — Agent 3 in the CMO hierarchy.

Manages paid acquisition across Meta Ads (and future TikTok/Google).
Wraps MetaAdsClient and DecisionEngine for campaign creation,
optimization, A/B testing, creative rotation, and budget management.

Owned channels:
- Meta Ads (Facebook + Instagram)
- TikTok Ads (planned)
- Google Ads (planned)
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from .base_agent import BaseAgent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DAILY_BUDGET_CENTS = 2500          # EUR 25.00
DEFAULT_OBJECTIVE = "OUTCOME_SALES"
FATIGUE_CTR_DROP_PCT = 0.25                # 25 % decline = fatigued
FATIGUE_MIN_IMPRESSIONS = 3000             # need enough data to judge
FATIGUE_FREQUENCY_THRESHOLD = 3.5          # high frequency = stale creative
AB_TEST_SPLIT_BUDGET_PCT = 0.50           # even split by default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _cents(eur: float) -> int:
    """Convert EUR amount to cents for Meta API."""
    return int(round(eur * 100))


def _eur(cents_val: int) -> float:
    """Convert cents to EUR for display."""
    return cents_val / 100.0


# ---------------------------------------------------------------------------
# Lazy service accessors
# ---------------------------------------------------------------------------

_meta_client: Optional[Any] = None
_decision_engine: Optional[Any] = None
_asset_store: Optional[Any] = None


def _get_meta_client():
    """Lazy-load MetaAdsClient from the parent-dir meta_decision_engine."""
    global _meta_client
    if _meta_client is None:
        from meta_decision_engine import MetaAdsClient
        token = os.getenv("META_ACCESS_TOKEN", "")
        account = os.getenv("META_AD_ACCOUNT_ID", "668790152408430")
        if account.startswith("act_"):
            account = account[4:]
        _meta_client = MetaAdsClient(access_token=token, ad_account_id=account)
    return _meta_client


def _get_decision_engine():
    """Lazy-load the DecisionEngine (aliased as MetaDecisionEngine)."""
    global _decision_engine
    if _decision_engine is None:
        from meta_decision_engine import DecisionEngine, EngineConfig
        token = os.getenv("META_ACCESS_TOKEN", "")
        account = os.getenv("META_AD_ACCOUNT_ID", "668790152408430")
        if account.startswith("act_"):
            account = account[4:]
        _decision_engine = DecisionEngine(
            access_token=token,
            ad_account_id=account,
            config=EngineConfig(),
        )
    return _decision_engine


def _get_asset_store():
    """Lazy-load the ContentAssetStore."""
    global _asset_store
    if _asset_store is None:
        from .content_asset_store import ContentAssetStore
        _asset_store = ContentAssetStore()
    return _asset_store


# ---------------------------------------------------------------------------
# AcquisitionAgent
# ---------------------------------------------------------------------------

class AcquisitionAgent(BaseAgent):
    """
    Manages paid acquisition across Meta Ads.

    Task types handled:
        create_campaign_from_asset  - Build a full campaign from a content asset
        optimize_campaigns          - Run decision engine, surface actions for CMO
        setup_ab_test               - A/B test two assets in one campaign
        rotate_creatives            - Swap fatigued ads for fresh content
        generate_performance_report - ROAS / CPA / CTR summary
        adjust_budgets              - Reallocate spend based on performance
    """

    agent_name: str = "acquisition"

    def __init__(self):
        super().__init__()

        # Register all task handlers
        self.register_handler("create_campaign_from_asset", self._handle_create_campaign_from_asset)
        self.register_handler("optimize_campaigns", self._handle_optimize_campaigns)
        self.register_handler("setup_ab_test", self._handle_setup_ab_test)
        self.register_handler("rotate_creatives", self._handle_rotate_creatives)
        self.register_handler("generate_performance_report", self._handle_generate_performance_report)
        self.register_handler("adjust_budgets", self._handle_adjust_budgets)

    # ------------------------------------------------------------------
    # BaseAgent abstract method
    # ------------------------------------------------------------------

    def get_supported_tasks(self) -> List[str]:
        return list(self._task_handlers.keys())

    # ==================================================================
    # 1. create_campaign_from_asset
    # ==================================================================

    async def _handle_create_campaign_from_asset(self, params: dict) -> dict:
        """
        Create a full Meta campaign from a content asset.

        Expected params:
            asset_uuid  (str)  - UUID of the content asset to use as creative
            targeting   (dict) - Targeting spec (age_min, age_max, genders, countries, etc.)
            daily_budget_eur (float) - Daily budget in EUR (default 25)
            campaign_name (str) - Optional campaign name override
            objective   (str)  - Meta objective (default OUTCOME_SALES)
            advantage_audience (bool) - Enable Advantage+ audience (default True)

        Returns:
            campaign_id, adset_id, ad_id, creative_id
        """
        asset_uuid = params.get("asset_uuid")
        if not asset_uuid:
            raise ValueError("asset_uuid is required")

        store = _get_asset_store()
        asset = await store.get_asset(asset_uuid)
        if not asset:
            raise ValueError(f"Content asset {asset_uuid} not found")

        client = _get_meta_client()

        targeting = params.get("targeting") or client.build_skincare_targeting_preset()
        daily_budget_eur = params.get("daily_budget_eur", 25.0)
        objective = params.get("objective", DEFAULT_OBJECTIVE)
        advantage_audience = params.get("advantage_audience", True)

        # Derive names
        base_name = params.get("campaign_name") or f"Mirai - {asset.title[:40]}"
        timestamp_tag = datetime.utcnow().strftime("%m%d")

        # --- Step 1: Create campaign (PAUSED) ---
        campaign_result = client.create_campaign(
            name=f"{base_name} [{timestamp_tag}]",
            objective=objective,
            status="PAUSED",
        )
        if not campaign_result.get("success"):
            raise RuntimeError(f"Campaign creation failed: {campaign_result}")
        campaign_id = campaign_result["id"]

        # --- Step 2: Create ad set ---
        pixel_id = os.getenv("META_PIXEL_ID", "")
        promoted_object = {"pixel_id": pixel_id} if pixel_id else None

        adset_result = client.create_adset(
            campaign_id=campaign_id,
            name=f"{base_name} - AdSet [{timestamp_tag}]",
            daily_budget=_cents(daily_budget_eur),
            targeting=targeting,
            optimization_goal="OFFSITE_CONVERSIONS",
            status="PAUSED",
            advantage_audience=advantage_audience,
            promoted_object=promoted_object,
        )
        if not adset_result.get("success"):
            raise RuntimeError(f"Ad set creation failed: {adset_result}")
        adset_id = adset_result["id"]

        # --- Step 3: Upload creative / resolve creative ID ---
        creative_id = await self._resolve_creative_id(asset, client)

        # --- Step 4: Create ad ---
        ad_result = client.create_ad(
            adset_id=adset_id,
            creative_id=creative_id,
            name=f"{base_name} - Ad [{timestamp_tag}]",
            status="PAUSED",
        )
        if not ad_result.get("success"):
            raise RuntimeError(f"Ad creation failed: {ad_result}")
        ad_id = ad_result["id"]

        # --- Step 5: Mark asset as used in paid ---
        await store.mark_used(asset_uuid, "paid", ad_id)

        # --- Log the decision ---
        await self.log_decision(
            decision_type="campaign_created",
            context={
                "asset_uuid": asset_uuid,
                "targeting": targeting,
                "daily_budget_eur": daily_budget_eur,
            },
            decision={
                "campaign_id": campaign_id,
                "adset_id": adset_id,
                "ad_id": ad_id,
                "creative_id": creative_id,
            },
            reasoning=f"Created PAUSED campaign from asset '{asset.title}' with EUR {daily_budget_eur}/day budget.",
            confidence=0.9,
            requires_approval=True,
        )

        return {
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "ad_id": ad_id,
            "creative_id": creative_id,
            "status": "PAUSED",
            "daily_budget_eur": daily_budget_eur,
            "message": "Campaign created in PAUSED state. Activate via CMO approval.",
        }

    # ==================================================================
    # 2. optimize_campaigns
    # ==================================================================

    async def _handle_optimize_campaigns(self, params: dict) -> dict:
        """
        Run the Meta Decision Engine analysis and create approval tasks
        for the CMO agent for any recommended actions.

        Expected params:
            campaign_id (str)  - Optional: analyse a specific campaign
            date_range  (str)  - Meta date preset (default 'last_7d')
            auto_execute (bool) - If True, execute low-risk actions automatically
        """
        engine = _get_decision_engine()
        campaign_id = params.get("campaign_id")
        date_range = params.get("date_range", "last_7d")

        report = engine.analyze_campaign(
            campaign_id=campaign_id,
            date_range=date_range,
        )

        decisions = report.get("decisions", [])
        alerts = report.get("alerts", [])
        recommendations = report.get("recommendations", [])

        # Create CMO approval tasks for high-priority decisions
        approval_task_ids = []
        for decision in decisions:
            decision_type = decision.get("decision_type", {})
            dt_value = decision_type.get("value") if isinstance(decision_type, dict) else str(decision_type)
            priority_raw = decision.get("priority", {})
            priority_value = priority_raw.get("value") if isinstance(priority_raw, dict) else str(priority_raw)

            if dt_value in ("SCALE", "PAUSE"):
                task_id = await self.create_task(
                    target_agent="cmo",
                    task_type="approve_optimization",
                    params={
                        "source": "acquisition_agent",
                        "decision": decision,
                        "report_health_score": report.get("health_score"),
                        "date_range": date_range,
                    },
                    priority="high" if priority_value in ("CRITICAL", "HIGH") else "normal",
                )
                approval_task_ids.append(task_id)

        # Log the analysis
        await self.log_decision(
            decision_type="campaign_optimization_analysis",
            context={
                "campaign_id": campaign_id,
                "date_range": date_range,
                "num_decisions": len(decisions),
                "num_alerts": len(alerts),
            },
            decision={
                "health_score": report.get("health_score"),
                "recommendations_count": len(recommendations),
                "approval_tasks_created": len(approval_task_ids),
            },
            reasoning=(
                f"Analyzed campaigns ({date_range}). "
                f"Health score: {report.get('health_score')}/100. "
                f"{len(decisions)} decisions, {len(alerts)} alerts. "
                f"Created {len(approval_task_ids)} CMO approval tasks."
            ),
            confidence=0.8,
            requires_approval=False,
        )

        return {
            "health_score": report.get("health_score"),
            "total_decisions": len(decisions),
            "total_alerts": len(alerts),
            "total_recommendations": len(recommendations),
            "approval_tasks_created": approval_task_ids,
            "account_summary": report.get("account_summary"),
            "recommendations": recommendations,
        }

    # ==================================================================
    # 3. setup_ab_test
    # ==================================================================

    async def _handle_setup_ab_test(self, params: dict) -> dict:
        """
        A/B test two content assets in a single campaign with two ads.

        Expected params:
            asset_uuid_a (str)  - First asset UUID (variant A)
            asset_uuid_b (str)  - Second asset UUID (variant B)
            targeting    (dict) - Shared targeting spec
            daily_budget_eur (float) - Total daily budget (split evenly)
            campaign_name (str) - Optional name
        """
        asset_uuid_a = params.get("asset_uuid_a")
        asset_uuid_b = params.get("asset_uuid_b")
        if not asset_uuid_a or not asset_uuid_b:
            raise ValueError("Both asset_uuid_a and asset_uuid_b are required")

        store = _get_asset_store()
        asset_a = await store.get_asset(asset_uuid_a)
        asset_b = await store.get_asset(asset_uuid_b)
        if not asset_a:
            raise ValueError(f"Asset A ({asset_uuid_a}) not found")
        if not asset_b:
            raise ValueError(f"Asset B ({asset_uuid_b}) not found")

        client = _get_meta_client()

        targeting = params.get("targeting") or client.build_skincare_targeting_preset()
        daily_budget_eur = params.get("daily_budget_eur", 30.0)
        timestamp_tag = datetime.utcnow().strftime("%m%d")
        base_name = params.get("campaign_name") or f"Mirai AB Test [{timestamp_tag}]"

        # --- Campaign ---
        campaign_result = client.create_campaign(
            name=base_name,
            objective=DEFAULT_OBJECTIVE,
            status="PAUSED",
        )
        if not campaign_result.get("success"):
            raise RuntimeError(f"Campaign creation failed: {campaign_result}")
        campaign_id = campaign_result["id"]

        # --- Single ad set with full budget ---
        pixel_id = os.getenv("META_PIXEL_ID", "")
        promoted_object = {"pixel_id": pixel_id} if pixel_id else None

        adset_result = client.create_adset(
            campaign_id=campaign_id,
            name=f"{base_name} - AdSet",
            daily_budget=_cents(daily_budget_eur),
            targeting=targeting,
            optimization_goal="OFFSITE_CONVERSIONS",
            status="PAUSED",
            advantage_audience=True,
            promoted_object=promoted_object,
        )
        if not adset_result.get("success"):
            raise RuntimeError(f"Ad set creation failed: {adset_result}")
        adset_id = adset_result["id"]

        # --- Two ads (variant A and B) ---
        creative_id_a = await self._resolve_creative_id(asset_a, client)
        creative_id_b = await self._resolve_creative_id(asset_b, client)

        ad_a_result = client.create_ad(
            adset_id=adset_id,
            creative_id=creative_id_a,
            name=f"Variant A - {asset_a.title[:30]}",
            status="PAUSED",
        )
        ad_b_result = client.create_ad(
            adset_id=adset_id,
            creative_id=creative_id_b,
            name=f"Variant B - {asset_b.title[:30]}",
            status="PAUSED",
        )

        # Mark assets
        if ad_a_result.get("success"):
            await store.mark_used(asset_uuid_a, "paid", ad_a_result["id"])
        if ad_b_result.get("success"):
            await store.mark_used(asset_uuid_b, "paid", ad_b_result["id"])

        await self.log_decision(
            decision_type="ab_test_created",
            context={
                "asset_uuid_a": asset_uuid_a,
                "asset_uuid_b": asset_uuid_b,
                "daily_budget_eur": daily_budget_eur,
            },
            decision={
                "campaign_id": campaign_id,
                "adset_id": adset_id,
                "ad_a_id": ad_a_result.get("id"),
                "ad_b_id": ad_b_result.get("id"),
            },
            reasoning=(
                f"Created A/B test: '{asset_a.title}' vs '{asset_b.title}' "
                f"with EUR {daily_budget_eur}/day. Both ads in single ad set "
                f"so Meta distributes impressions to the winner."
            ),
            confidence=0.85,
            requires_approval=True,
        )

        return {
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "variant_a": {
                "ad_id": ad_a_result.get("id"),
                "creative_id": creative_id_a,
                "asset_title": asset_a.title,
            },
            "variant_b": {
                "ad_id": ad_b_result.get("id"),
                "creative_id": creative_id_b,
                "asset_title": asset_b.title,
            },
            "status": "PAUSED",
            "daily_budget_eur": daily_budget_eur,
        }

    # ==================================================================
    # 4. rotate_creatives
    # ==================================================================

    async def _handle_rotate_creatives(self, params: dict) -> dict:
        """
        Find fatigued ads (declining CTR / high frequency) and swap them
        with fresh content assets.

        Expected params:
            campaign_id      (str)  - Optional: limit to one campaign
            date_range       (str)  - Date preset for metrics (default 'last_7d')
            replacement_pool (list) - Optional list of asset UUIDs to use
        """
        client = _get_meta_client()
        store = _get_asset_store()
        date_range = params.get("date_range", "last_7d")
        campaign_id = params.get("campaign_id")

        # Gather active ads with performance data
        fatigued_ads = []
        campaigns = client.get_campaigns()

        for campaign in campaigns:
            if campaign.get("effective_status") != "ACTIVE":
                continue
            if campaign_id and campaign["id"] != campaign_id:
                continue

            adsets = client.get_adsets(campaign["id"])
            for adset in adsets:
                if adset.get("effective_status") != "ACTIVE":
                    continue

                ads = client.get_ads(adset["id"])
                for ad in ads:
                    if ad.get("effective_status") != "ACTIVE":
                        continue

                    metrics = client.get_insights(
                        ad["id"], level="ad", date_preset=date_range
                    )

                    is_fatigued = self._detect_fatigue(metrics)
                    if is_fatigued:
                        fatigued_ads.append({
                            "ad_id": ad["id"],
                            "ad_name": ad.get("name", ""),
                            "adset_id": adset["id"],
                            "campaign_id": campaign["id"],
                            "ctr": metrics.ctr,
                            "frequency": metrics.frequency,
                            "impressions": metrics.impressions,
                            "fatigue_reason": is_fatigued,
                        })

        if not fatigued_ads:
            return {
                "fatigued_count": 0,
                "rotated_count": 0,
                "message": "No fatigued ads detected.",
            }

        # Find replacement assets (unused in paid, status = approved or ready)
        replacement_uuids = params.get("replacement_pool") or []
        if not replacement_uuids:
            available_assets = await store.list_assets(
                status="approved",
                used_in_paid=False,
                limit=len(fatigued_ads) * 2,
            )
            # Fallback: also check 'ready' status
            if len(available_assets) < len(fatigued_ads):
                ready_assets = await store.list_assets(
                    status="ready",
                    used_in_paid=False,
                    limit=len(fatigued_ads) * 2,
                )
                available_assets.extend(ready_assets)
            replacement_uuids = [a.uuid for a in available_assets]

        rotated = []
        for i, fatigued in enumerate(fatigued_ads):
            if i >= len(replacement_uuids):
                break  # No more replacements available

            replacement_uuid = replacement_uuids[i]
            replacement_asset = await store.get_asset(replacement_uuid)
            if not replacement_asset:
                continue

            # Pause the fatigued ad
            client.update_status(fatigued["ad_id"], "PAUSED")

            # Create replacement ad in the same ad set
            try:
                creative_id = await self._resolve_creative_id(replacement_asset, client)
                new_ad = client.create_ad(
                    adset_id=fatigued["adset_id"],
                    creative_id=creative_id,
                    name=f"Rotation - {replacement_asset.title[:30]}",
                    status="ACTIVE",
                )
                if new_ad.get("success"):
                    await store.mark_used(replacement_uuid, "paid", new_ad["id"])
                    rotated.append({
                        "paused_ad_id": fatigued["ad_id"],
                        "paused_ad_name": fatigued["ad_name"],
                        "new_ad_id": new_ad["id"],
                        "new_asset_uuid": replacement_uuid,
                        "new_asset_title": replacement_asset.title,
                    })
            except Exception as e:
                print(f"[AcquisitionAgent] Rotation failed for {fatigued['ad_id']}: {e}")

        await self.log_decision(
            decision_type="creative_rotation",
            context={
                "fatigued_count": len(fatigued_ads),
                "replacements_available": len(replacement_uuids),
            },
            decision={
                "rotated": rotated,
            },
            reasoning=(
                f"Detected {len(fatigued_ads)} fatigued ads. "
                f"Rotated {len(rotated)} with fresh creatives."
            ),
            confidence=0.75,
            requires_approval=False,
        )

        return {
            "fatigued_count": len(fatigued_ads),
            "rotated_count": len(rotated),
            "rotated": rotated,
            "fatigued_details": fatigued_ads,
        }

    # ==================================================================
    # 5. generate_performance_report
    # ==================================================================

    async def _handle_generate_performance_report(self, params: dict) -> dict:
        """
        Generate a ROAS / CPA / CTR summary for the CMO.

        Expected params:
            date_range     (str)  - Meta date preset (default 'last_7d')
            campaign_id    (str)  - Optional: single campaign
            include_ads    (bool) - Include per-ad breakdown (default False)
            include_diagnosis (bool) - Include CPM diagnosis (default False)
        """
        engine = _get_decision_engine()
        client = _get_meta_client()
        date_range = params.get("date_range", "last_7d")
        campaign_id = params.get("campaign_id")
        include_ads = params.get("include_ads", False)
        include_diagnosis = params.get("include_diagnosis", False)

        # Account-level quick status
        quick_status = engine.get_quick_status(date_range)

        # Full analysis for recommendations
        full_report = engine.analyze_campaign(
            campaign_id=campaign_id,
            date_range=date_range,
        )

        report = {
            "generated_at": _now_iso(),
            "date_range": date_range,
            "account_overview": quick_status,
            "health_score": full_report.get("health_score", 0),
            "campaigns": [],
            "top_recommendations": full_report.get("recommendations", [])[:5],
            "alerts": full_report.get("alerts", []),
        }

        # Per-campaign breakdown
        for camp_data in full_report.get("campaigns", []):
            camp_summary = {
                "id": camp_data.get("id"),
                "name": camp_data.get("name"),
                "status": camp_data.get("status"),
                "metrics": camp_data.get("metrics", {}),
                "adset_count": len(camp_data.get("adsets", [])),
            }

            if include_ads:
                camp_summary["adsets"] = []
                for adset_data in camp_data.get("adsets", []):
                    adset_summary = {
                        "id": adset_data.get("id"),
                        "name": adset_data.get("name"),
                        "metrics": adset_data.get("metrics", {}),
                        "ads": adset_data.get("ads", []),
                    }
                    camp_summary["adsets"].append(adset_summary)

            report["campaigns"].append(camp_summary)

        # Optional CPM diagnosis
        if include_diagnosis:
            try:
                diagnosis = client.diagnose_high_cpm(date_preset=date_range)
                report["cpm_diagnosis"] = diagnosis
            except Exception as e:
                report["cpm_diagnosis"] = {"error": str(e)}

        # Use AI to generate a human-readable summary
        try:
            ai_summary = await self._generate_ai_summary(report)
            report["ai_summary"] = ai_summary
        except Exception:
            report["ai_summary"] = None

        return report

    async def _generate_ai_summary(self, report: dict) -> str:
        """Use AI to create a concise performance summary for the CMO."""
        overview = report.get("account_overview", {})
        prompt = (
            f"Summarize this Meta Ads performance report for a CMO in 3-5 bullet points.\n\n"
            f"Date range: {report.get('date_range')}\n"
            f"Health score: {report.get('health_score')}/100\n"
            f"Spend: {overview.get('spend', 'N/A')}\n"
            f"Impressions: {overview.get('impressions', 0)}\n"
            f"Clicks: {overview.get('clicks', 0)}\n"
            f"CTR: {overview.get('ctr', 'N/A')}\n"
            f"CPC: {overview.get('cpc', 'N/A')}\n"
            f"Purchases: {overview.get('purchases', 0)}\n"
            f"CPA: {overview.get('cpa', 'N/A')}\n"
            f"ROAS: {overview.get('roas', 'N/A')}\n"
            f"Alerts: {len(report.get('alerts', []))}\n"
            f"Campaigns: {len(report.get('campaigns', []))}\n"
            f"\nProvide actionable insights. Be concise."
        )
        return await self.call_ai_text(
            prompt=prompt,
            system_prompt="You are a performance marketing analyst for a DTC skincare brand.",
            temperature=0.4,
        )

    # ==================================================================
    # 6. adjust_budgets
    # ==================================================================

    async def _handle_adjust_budgets(self, params: dict) -> dict:
        """
        Reallocate spend across ad sets based on performance.

        Expected params:
            campaign_id    (str)   - Campaign to rebalance
            date_range     (str)   - Date preset for metrics (default 'last_7d')
            total_daily_eur (float) - Optional: new total daily budget
            strategy       (str)   - 'performance' (default) or 'equal'
        """
        client = _get_meta_client()
        campaign_id = params.get("campaign_id")
        date_range = params.get("date_range", "last_7d")
        total_daily_eur = params.get("total_daily_eur")
        strategy = params.get("strategy", "performance")

        if not campaign_id:
            raise ValueError("campaign_id is required for budget adjustment")

        # Get all active ad sets in the campaign
        adsets = client.get_adsets(campaign_id)
        active_adsets = [a for a in adsets if a.get("effective_status") == "ACTIVE"]

        if not active_adsets:
            return {"error": "No active ad sets found in campaign", "campaign_id": campaign_id}

        # Collect performance data for each ad set
        adset_perf = []
        for adset in active_adsets:
            metrics = client.get_insights(adset["id"], level="adset", date_preset=date_range)
            current_budget_cents = int(adset.get("daily_budget", 0))
            adset_perf.append({
                "id": adset["id"],
                "name": adset.get("name", ""),
                "current_budget_eur": _eur(current_budget_cents),
                "spend": metrics.spend,
                "ctr": metrics.ctr,
                "cpc": metrics.cpc,
                "roas": metrics.roas,
                "purchases": metrics.purchases,
                "cost_per_purchase": metrics.cost_per_purchase,
                "impressions": metrics.impressions,
            })

        # Determine total budget
        if total_daily_eur is None:
            total_daily_eur = sum(a["current_budget_eur"] for a in adset_perf)
        if total_daily_eur <= 0:
            return {"error": "Total budget must be positive"}

        # Calculate new allocations
        adjustments = []
        if strategy == "equal":
            per_adset = total_daily_eur / len(adset_perf)
            for ap in adset_perf:
                adjustments.append({**ap, "new_budget_eur": round(per_adset, 2)})
        else:
            # Performance-based: weight by ROAS or inverse CPA
            adjustments = self._calculate_performance_allocation(adset_perf, total_daily_eur)

        # Apply budget changes
        applied = []
        for adj in adjustments:
            new_cents = _cents(adj["new_budget_eur"])
            old_cents = _cents(adj["current_budget_eur"])

            if abs(new_cents - old_cents) < 100:
                # Skip trivial changes (< EUR 1 difference)
                adj["action"] = "no_change"
                applied.append(adj)
                continue

            result = client.update_budget(adj["id"], new_cents)
            adj["action"] = "updated"
            adj["api_result"] = result
            applied.append(adj)

        await self.log_decision(
            decision_type="budget_adjustment",
            context={
                "campaign_id": campaign_id,
                "strategy": strategy,
                "total_daily_eur": total_daily_eur,
                "adset_count": len(active_adsets),
            },
            decision={
                "adjustments": [
                    {
                        "adset_id": a["id"],
                        "old_budget": a["current_budget_eur"],
                        "new_budget": a["new_budget_eur"],
                        "action": a.get("action"),
                    }
                    for a in applied
                ],
            },
            reasoning=(
                f"Reallocated EUR {total_daily_eur}/day across {len(active_adsets)} "
                f"ad sets using '{strategy}' strategy."
            ),
            confidence=0.7,
            requires_approval=True,
        )

        return {
            "campaign_id": campaign_id,
            "strategy": strategy,
            "total_daily_eur": total_daily_eur,
            "adjustments": applied,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calculate_performance_allocation(
        self, adset_perf: List[dict], total_budget: float
    ) -> List[dict]:
        """
        Allocate budget proportionally to performance.

        Uses a composite score:
          - ROAS weight: 0.4
          - CTR weight: 0.3
          - Inverse CPA weight: 0.3 (lower CPA = better)

        Ad sets with zero data get a baseline allocation.
        """
        MIN_ALLOCATION_PCT = 0.10  # Each ad set gets at least 10 %

        scores = []
        for ap in adset_perf:
            roas_score = min(ap["roas"] / 3.0, 1.0) if ap["roas"] > 0 else 0.1
            ctr_score = min(ap["ctr"] / 2.0, 1.0) if ap["ctr"] > 0 else 0.1
            cpa = ap["cost_per_purchase"]
            cpa_score = min(25.0 / cpa, 1.0) if cpa > 0 else 0.1

            composite = (roas_score * 0.4) + (ctr_score * 0.3) + (cpa_score * 0.3)
            # Ensure minimum score so every ad set gets some budget
            composite = max(composite, 0.05)
            scores.append(composite)

        total_score = sum(scores) or 1.0

        results = []
        for i, ap in enumerate(adset_perf):
            raw_pct = scores[i] / total_score
            # Enforce minimum allocation
            capped_pct = max(raw_pct, MIN_ALLOCATION_PCT)
            new_budget = round(total_budget * capped_pct, 2)
            results.append({
                **ap,
                "score": round(scores[i], 4),
                "allocation_pct": round(capped_pct * 100, 1),
                "new_budget_eur": new_budget,
            })

        # Normalize so total matches exactly
        allocated_total = sum(r["new_budget_eur"] for r in results)
        if allocated_total > 0 and abs(allocated_total - total_budget) > 0.01:
            factor = total_budget / allocated_total
            for r in results:
                r["new_budget_eur"] = round(r["new_budget_eur"] * factor, 2)

        return results

    def _detect_fatigue(self, metrics) -> Optional[str]:
        """
        Detect creative fatigue from ad metrics.

        Returns a reason string if fatigued, None otherwise.
        """
        if metrics.impressions < FATIGUE_MIN_IMPRESSIONS:
            return None

        reasons = []

        # High frequency indicates the same users keep seeing the ad
        if metrics.frequency >= FATIGUE_FREQUENCY_THRESHOLD:
            reasons.append(
                f"High frequency ({metrics.frequency:.1f} >= {FATIGUE_FREQUENCY_THRESHOLD})"
            )

        # Low CTR combined with enough impressions
        if metrics.ctr < 0.5 and metrics.impressions >= 5000:
            reasons.append(f"Low CTR ({metrics.ctr:.2f}%) with {metrics.impressions} impressions")

        if not reasons:
            return None

        return "; ".join(reasons)

    async def _resolve_creative_id(self, asset, client) -> str:
        """
        Resolve or create a Meta ad creative ID from a content asset.

        If the asset already has an ad_creative_ids entry, use the first one.
        Otherwise, attempt to find a matching creative in the account by name,
        or raise an error indicating manual creative upload is needed.
        """
        # Check if asset already has a creative ID
        if asset.ad_creative_ids:
            return asset.ad_creative_ids[0]

        # Try to find by name in existing creatives
        existing = client.get_creatives(limit=100)
        asset_title_lower = asset.title.lower().strip()
        for creative in existing:
            creative_name = (creative.get("name") or "").lower().strip()
            if asset_title_lower and asset_title_lower in creative_name:
                return creative["id"]

        # If the asset has an image URL, we could create a creative via the API,
        # but that requires page_id and additional setup. For now, raise an error
        # so the operator can upload the creative manually or the content agent
        # can handle it.
        if asset.primary_image_url or asset.primary_image_data:
            raise ValueError(
                f"Asset '{asset.title}' has image data but no ad creative ID. "
                f"Upload the creative to Meta Ads Manager first, or use the "
                f"content agent to create the creative via the Marketing API."
            )

        raise ValueError(
            f"No ad creative found for asset '{asset.title}' (uuid={asset.uuid}). "
            f"Create a creative in Meta Ads Manager and link it to this asset."
        )
