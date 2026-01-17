"""
Meta Ads Decision Engine
AI-powered campaign optimization for Mirai Skin

Goals:
- Target CPA: $20 (€18.50) per purchase
- Conversion funnel: Click → Quiz Complete → Add to Cart → Purchase
- 2% click-to-purchase conversion rate target
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import requests

# Configuration
META_API_VERSION = "v18.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"


class DecisionType(Enum):
    SCALE = "SCALE"
    PAUSE = "PAUSE"
    MAINTAIN = "MAINTAIN"
    LEARNING = "LEARNING"
    ALERT = "ALERT"


class Priority(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class PerformanceMetrics:
    """Campaign/AdSet/Ad performance metrics"""
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    spend: float = 0.0
    ctr: float = 0.0
    cpc: float = 0.0
    cpm: float = 0.0
    frequency: float = 0.0
    # Conversion events
    quiz_starts: int = 0
    quiz_completes: int = 0
    add_to_carts: int = 0
    purchases: int = 0
    purchase_value: float = 0.0
    # Calculated costs
    cost_per_quiz_complete: float = 0.0
    cost_per_add_to_cart: float = 0.0
    cost_per_purchase: float = 0.0
    # ROAS
    roas: float = 0.0


@dataclass
class Decision:
    """Optimization decision"""
    entity_type: str  # campaign, adset, ad
    entity_id: str
    entity_name: str
    decision_type: DecisionType
    priority: Priority
    reason: str
    metrics: Dict[str, Any]
    recommended_action: str
    auto_execute: bool = False


@dataclass
class EngineConfig:
    """Decision engine configuration"""
    # CPA targets (in EUR) - Updated Jan 2026
    # More realistic targets for early-stage campaigns
    target_cpa: float = 25.00  # Ideal CPA we aim for
    acceptable_cpa: float = 35.00  # Acceptable CPA during learning
    max_cpa: float = 40.00  # Maximum before alert (user's budget limit)
    alert_cpa: float = 50.00  # Critical alert threshold

    # CTR thresholds - more lenient during learning
    min_ctr: float = 0.6  # Below this = concern
    target_ctr: float = 1.2  # Good CTR for cold traffic
    excellent_ctr: float = 2.0  # Excellent performance

    # CPC thresholds (EUR) - adjusted for high CPM markets
    target_cpc: float = 0.50
    max_cpc: float = 0.80

    # CPM thresholds (EUR) - new metric for monitoring
    target_cpm: float = 15.00  # Ideal CPM
    max_cpm: float = 25.00  # Above this = audience too narrow/expensive

    # Minimum data for decisions - more data needed for reliability
    min_impressions: int = 1500  # Need more data before deciding
    min_clicks: int = 30
    min_spend: float = 15.0

    # Learning phase - TIME BASED PROTECTION
    learning_phase_impressions: int = 1000  # Increased for better data
    learning_phase_hours: int = 72  # Minimum 3 days before kill decisions
    min_hours_before_pause: int = 120  # 5 days minimum before pausing
    min_spend_before_pause: float = 50.0  # Minimum €50 spent before pause decision

    # Campaign maturity phases (hours)
    phase_new: int = 72  # 0-72 hours = NEW (protected)
    phase_learning: int = 240  # 72-240 hours (10 days) = LEARNING
    # After 240 hours = MATURE (full optimization)

    # Budget rules
    scale_budget_increase: float = 0.20  # 20% increase
    scale_min_roas: float = 1.5  # Lowered - 1.5x ROAS is good for early stage

    # Auto-actions
    auto_pause_underperformers: bool = False
    auto_scale_winners: bool = False

    # Funnel conversion targets (more realistic)
    click_to_quiz_rate: float = 0.25  # 25% of clicks start quiz
    quiz_complete_rate: float = 0.50  # 50% complete quiz
    quiz_to_atc_rate: float = 0.10  # 10% add to cart
    atc_to_purchase_rate: float = 0.30  # 30% purchase


class MetaAdsClient:
    """Meta Marketing API client"""

    def __init__(self, access_token: str, ad_account_id: str):
        self.access_token = access_token
        self.ad_account_id = ad_account_id

    def _request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        url = f"{META_API_BASE}{endpoint}"
        params = {"access_token": self.access_token}

        if method == "GET":
            response = requests.get(url, params={**params, **(data or {})})
        else:
            response = requests.post(url, params=params, data=data)

        return response.json()

    def get_campaigns(self, status_filter: str = None) -> List[dict]:
        """Get all campaigns"""
        fields = "id,name,status,effective_status,daily_budget,lifetime_budget,objective,created_time,start_time"
        endpoint = f"/act_{self.ad_account_id}/campaigns?fields={fields}"
        result = self._request(endpoint)
        return result.get("data", [])

    def get_adsets(self, campaign_id: str = None) -> List[dict]:
        """Get ad sets"""
        fields = "id,name,status,effective_status,daily_budget,campaign_id,optimization_goal,created_time,start_time"
        endpoint = f"/act_{self.ad_account_id}/adsets?fields={fields}"
        if campaign_id:
            endpoint += f"&filtering=[{{\"field\":\"campaign.id\",\"operator\":\"EQUAL\",\"value\":\"{campaign_id}\"}}]"
        result = self._request(endpoint)
        return result.get("data", [])

    def get_ads(self, adset_id: str = None) -> List[dict]:
        """Get ads"""
        fields = "id,name,status,effective_status,adset_id,created_time"
        endpoint = f"/act_{self.ad_account_id}/ads?fields={fields}"
        if adset_id:
            endpoint += f"&filtering=[{{\"field\":\"adset.id\",\"operator\":\"EQUAL\",\"value\":\"{adset_id}\"}}]"
        result = self._request(endpoint)
        return result.get("data", [])

    def get_insights(self, object_id: str, level: str = "account",
                     date_preset: str = "today") -> PerformanceMetrics:
        """Get insights for campaign/adset/ad"""
        fields = [
            "impressions", "reach", "clicks", "spend", "ctr", "cpc", "cpm",
            "frequency", "actions", "action_values", "cost_per_action_type"
        ]

        if level == "account":
            endpoint = f"/act_{self.ad_account_id}/insights"
        else:
            endpoint = f"/{object_id}/insights"

        endpoint += f"?fields={','.join(fields)}&date_preset={date_preset}"
        result = self._request(endpoint)

        data_list = result.get("data", [])
        data = data_list[0] if data_list else {}
        return self._parse_insights(data)

    def get_ad_quality_scores(self, ad_id: str, date_preset: str = "last_7d") -> dict:
        """
        Get ad quality/relevance scores from Meta

        Returns:
            quality_ranking: BELOW_AVERAGE_10, BELOW_AVERAGE_20, BELOW_AVERAGE_35,
                           AVERAGE, ABOVE_AVERAGE
            engagement_rate_ranking: Same scale
            conversion_rate_ranking: Same scale
        """
        fields = [
            "quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking",
            "impressions", "cpm", "ctr", "cpc"
        ]
        endpoint = f"/{ad_id}/insights?fields={','.join(fields)}&date_preset={date_preset}"
        result = self._request(endpoint)

        data_list = result.get("data", [])
        if not data_list:
            return {"error": "No data available yet (need more impressions)"}

        data = data_list[0]
        return {
            "quality_ranking": data.get("quality_ranking", "Unknown"),
            "engagement_rate_ranking": data.get("engagement_rate_ranking", "Unknown"),
            "conversion_rate_ranking": data.get("conversion_rate_ranking", "Unknown"),
            "impressions": data.get("impressions", 0),
            "cpm": data.get("cpm", 0),
            "ctr": data.get("ctr", 0),
            "cpc": data.get("cpc", 0),
        }

    def diagnose_high_cpm(self, date_preset: str = "last_7d") -> dict:
        """
        Diagnose why CPM is high and provide actionable recommendations

        Checks:
        1. Quality/relevance scores for each ad
        2. Audience size and targeting
        3. Bid strategy and budget
        4. Creative performance comparison
        """
        diagnosis = {
            "timestamp": datetime.now().isoformat(),
            "overall_cpm": 0,
            "issues": [],
            "recommendations": [],
            "ad_scores": [],
            "audience_analysis": {},
        }

        # Get all active campaigns
        campaigns = self.get_campaigns()
        active_campaigns = [c for c in campaigns if c.get("effective_status") == "ACTIVE"]

        if not active_campaigns:
            diagnosis["issues"].append("No active campaigns found")
            return diagnosis

        total_spend = 0
        total_impressions = 0

        for campaign in active_campaigns:
            campaign_id = campaign["id"]

            # Get adsets
            adsets = self.get_adsets(campaign_id)
            for adset in adsets:
                adset_id = adset["id"]

                # Get adset insights
                try:
                    insights = self.get_insights(adset_id, level="adset", date_preset=date_preset)
                    total_spend += insights.spend
                    total_impressions += insights.impressions

                    # Check targeting
                    adset_details = self._request(f"/{adset_id}?fields=targeting,optimization_goal,daily_budget,bid_strategy")
                    targeting = adset_details.get("targeting", {})

                    # Analyze audience
                    audience_info = {
                        "adset_name": adset.get("name"),
                        "age_range": f"{targeting.get('age_min', '?')}-{targeting.get('age_max', '?')}",
                        "countries": targeting.get("geo_locations", {}).get("countries", []),
                        "has_interests": bool(targeting.get("flexible_spec")),
                        "has_custom_audiences": bool(targeting.get("custom_audiences")),
                        "optimization_goal": adset_details.get("optimization_goal"),
                        "daily_budget": int(adset_details.get("daily_budget", 0)) / 100,  # cents to EUR
                        "bid_strategy": adset_details.get("bid_strategy"),
                        "cpm": insights.cpm,
                    }
                    diagnosis["audience_analysis"][adset.get("name")] = audience_info

                    # Flag issues
                    if insights.cpm > 50:
                        diagnosis["issues"].append(f"Very high CPM (€{insights.cpm:.2f}) on adset '{adset.get('name')}'")

                    if targeting.get("flexible_spec"):
                        interests = targeting.get("flexible_spec", [])
                        if interests:
                            diagnosis["issues"].append(f"Narrow interest targeting on '{adset.get('name')}' - try Advantage+ or broader")

                except Exception as e:
                    print(f"Error getting adset insights: {e}")

                # Get ads and their quality scores
                ads = self.get_ads(adset_id)
                for ad in ads:
                    ad_id = ad["id"]
                    try:
                        scores = self.get_ad_quality_scores(ad_id, date_preset)
                        scores["ad_name"] = ad.get("name")
                        scores["adset_name"] = adset.get("name")
                        diagnosis["ad_scores"].append(scores)

                        # Flag quality issues
                        if "BELOW_AVERAGE" in str(scores.get("quality_ranking", "")):
                            diagnosis["issues"].append(f"Low quality score on ad '{ad.get('name')}' - creative not resonating")
                        if "BELOW_AVERAGE" in str(scores.get("engagement_rate_ranking", "")):
                            diagnosis["issues"].append(f"Low engagement on ad '{ad.get('name')}' - try different creative")

                    except Exception as e:
                        diagnosis["ad_scores"].append({
                            "ad_name": ad.get("name"),
                            "error": str(e)
                        })

        # Calculate overall CPM
        if total_impressions > 0:
            diagnosis["overall_cpm"] = (total_spend / total_impressions) * 1000

        # Generate recommendations based on issues
        if diagnosis["overall_cpm"] > 50:
            diagnosis["recommendations"].extend([
                "🎯 AUDIENCE: Your CPM is very high. Try Advantage+ Audience (let Meta optimize) instead of interest targeting",
                "🌍 GEO: Test UK, Canada, or Australia - often 50% lower CPMs than US",
                "💰 BUDGET: Increase daily budget to €50+ to give Meta more optimization room",
            ])

        if any("quality" in issue.lower() for issue in diagnosis["issues"]):
            diagnosis["recommendations"].extend([
                "🎨 CREATIVE: Low quality scores = Meta thinks your ad doesn't match audience. Test new visuals",
                "📝 COPY: Try different headlines/primary text - current ones may not resonate",
            ])

        if any("engagement" in issue.lower() for issue in diagnosis["issues"]):
            diagnosis["recommendations"].extend([
                "🛑 SCROLL-STOPPING: Your creative isn't stopping people. Try: faces, bold colors, motion",
                "❓ VALUE PROP: Is 'AI skin analysis' compelling enough? Test benefit-focused hooks",
            ])

        if any("narrow" in issue.lower() for issue in diagnosis["issues"]):
            diagnosis["recommendations"].extend([
                "📢 BROADER: Remove interest targeting. Use Advantage+ to let Meta find converters",
                "🔄 LOOKALIKE: If you have quiz completers, build a lookalike audience from them",
            ])

        # Default recommendations if we don't have enough data
        if not diagnosis["recommendations"]:
            diagnosis["recommendations"] = [
                "⏳ Need more data - campaigns are very new. Wait 3-5 days for meaningful insights",
                "📊 Check back when you have 500+ impressions per ad for quality scores",
            ]

        return diagnosis

    def _parse_insights(self, data: dict) -> PerformanceMetrics:
        """Parse raw insights into PerformanceMetrics"""
        actions = {a["action_type"]: int(a["value"]) for a in data.get("actions", [])}
        action_values = {a["action_type"]: float(a["value"]) for a in data.get("action_values", [])}
        costs = {c["action_type"]: float(c["value"]) for c in data.get("cost_per_action_type", [])}

        spend = float(data.get("spend", 0))
        purchases = actions.get("purchase", 0) or actions.get("offsite_conversion.fb_pixel_purchase", 0)
        purchase_value = action_values.get("purchase", 0) or action_values.get("offsite_conversion.fb_pixel_purchase", 0)

        metrics = PerformanceMetrics(
            impressions=int(data.get("impressions", 0)),
            reach=int(data.get("reach", 0)),
            clicks=int(data.get("clicks", 0)),
            spend=spend,
            ctr=float(data.get("ctr", 0)),
            cpc=float(data.get("cpc", 0)),
            cpm=float(data.get("cpm", 0)),
            frequency=float(data.get("frequency", 0)),
            quiz_starts=actions.get("offsite_conversion.custom.StartAnalysis", 0),
            quiz_completes=actions.get("offsite_conversion.custom.CompleteAnalysis", 0),
            add_to_carts=actions.get("offsite_conversion.fb_pixel_add_to_cart", 0),
            purchases=purchases,
            purchase_value=purchase_value,
            cost_per_quiz_complete=costs.get("offsite_conversion.custom.CompleteAnalysis", 0),
            cost_per_add_to_cart=costs.get("offsite_conversion.fb_pixel_add_to_cart", 0),
            cost_per_purchase=costs.get("purchase", 0) or costs.get("offsite_conversion.fb_pixel_purchase", 0),
            roas=purchase_value / spend if spend > 0 else 0
        )

        return metrics

    def update_status(self, object_id: str, status: str) -> dict:
        """Update campaign/adset/ad status"""
        return self._request(f"/{object_id}", "POST", {"status": status})

    def update_budget(self, adset_id: str, daily_budget: int) -> dict:
        """Update ad set daily budget (in cents)"""
        return self._request(f"/{adset_id}", "POST", {"daily_budget": daily_budget})

    # ==================== CAMPAIGN CREATION METHODS ====================

    def create_campaign(self, name: str, objective: str = "OUTCOME_SALES",
                       status: str = "PAUSED") -> dict:
        """
        Create a new campaign

        Args:
            name: Campaign name
            objective: OUTCOME_SALES, OUTCOME_LEADS, OUTCOME_AWARENESS, etc.
            status: ACTIVE or PAUSED (default PAUSED for safety)

        Returns:
            {"id": "campaign_id", "success": true} or error
        """
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": "[]"  # Required for non-special ads
        }
        endpoint = f"/act_{self.ad_account_id}/campaigns"
        result = self._request(endpoint, "POST", data)
        if "id" in result:
            result["success"] = True
        return result

    def create_adset(self, campaign_id: str, name: str, daily_budget: int,
                    targeting: dict, optimization_goal: str = "OFFSITE_CONVERSIONS",
                    billing_event: str = "IMPRESSIONS",
                    status: str = "PAUSED",
                    advantage_audience: bool = False,
                    promoted_object: dict = None) -> dict:
        """
        Create a new ad set

        Args:
            campaign_id: Parent campaign ID
            name: Ad set name
            daily_budget: Daily budget in cents (e.g., 2500 = €25)
            targeting: Targeting spec dict (use build_targeting helper)
            optimization_goal: OFFSITE_CONVERSIONS, LINK_CLICKS, REACH, etc.
            billing_event: IMPRESSIONS, LINK_CLICKS
            status: ACTIVE or PAUSED
            advantage_audience: Enable Advantage+ Audience (let Meta optimize targeting)
            promoted_object: Pixel/page info for conversion optimization

        Returns:
            {"id": "adset_id", "success": true} or error
        """
        import json
        data = {
            "campaign_id": campaign_id,
            "name": name,
            "daily_budget": str(daily_budget),
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": json.dumps(targeting),
            "status": status
        }

        # Enable Advantage+ Audience (expansion_all)
        if advantage_audience:
            data["targeting_optimization_types"] = json.dumps(["expansion_all"])

        # Add promoted object for conversion campaigns
        if promoted_object:
            data["promoted_object"] = json.dumps(promoted_object)

        endpoint = f"/act_{self.ad_account_id}/adsets"
        result = self._request(endpoint, "POST", data)
        if "id" in result:
            result["success"] = True
        return result

    def create_ad(self, adset_id: str, creative_id: str, name: str,
                 status: str = "PAUSED") -> dict:
        """
        Create a new ad

        Args:
            adset_id: Parent ad set ID
            creative_id: Existing creative ID from the ad account
            name: Ad name
            status: ACTIVE or PAUSED

        Returns:
            {"id": "ad_id", "success": true} or error
        """
        import json
        data = {
            "adset_id": adset_id,
            "name": name,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": status
        }
        endpoint = f"/act_{self.ad_account_id}/ads"
        result = self._request(endpoint, "POST", data)
        if "id" in result:
            result["success"] = True
        return result

    def get_creatives(self, limit: int = 50) -> List[dict]:
        """
        Get available ad creatives from the account

        Returns list of creatives with id, name, thumbnail_url, status
        """
        fields = "id,name,thumbnail_url,status,effective_object_story_id,object_story_spec"
        endpoint = f"/act_{self.ad_account_id}/adcreatives?fields={fields}&limit={limit}"
        result = self._request(endpoint)
        return result.get("data", [])

    def get_ads_with_creatives(self, adset_id: str = None) -> List[dict]:
        """
        Get ads with their creative IDs for duplication

        Returns list of ads with id, name, creative_id, status
        """
        fields = "id,name,status,creative{id,name},adset_id"
        endpoint = f"/act_{self.ad_account_id}/ads?fields={fields}&limit=100"
        if adset_id:
            endpoint += f"&filtering=[{{\"field\":\"adset.id\",\"operator\":\"EQUAL\",\"value\":\"{adset_id}\"}}]"
        result = self._request(endpoint)
        return result.get("data", [])

    def duplicate_ads_to_adset(self, source_adset_id: str, target_adset_id: str,
                               name_suffix: str = "", status: str = "ACTIVE") -> List[dict]:
        """
        Copy all ads from one ad set to another

        Args:
            source_adset_id: Ad set to copy ads FROM
            target_adset_id: Ad set to copy ads TO
            name_suffix: Optional suffix to add to ad names
            status: Status for new ads (ACTIVE or PAUSED)

        Returns:
            List of created ad results
        """
        source_ads = self.get_ads_with_creatives(source_adset_id)
        results = []

        for ad in source_ads:
            creative = ad.get("creative", {})
            creative_id = creative.get("id")
            if not creative_id:
                continue

            # Create new ad name
            original_name = ad.get("name", "Ad")
            # Remove old ad set reference if present
            new_name = original_name
            if name_suffix:
                new_name = f"{original_name} {name_suffix}"

            result = self.create_ad(
                adset_id=target_adset_id,
                creative_id=creative_id,
                name=new_name,
                status=status
            )
            result["original_ad"] = original_name
            results.append(result)

        return results

    def setup_test_adsets(self, campaign_id: str, source_adset_id: str,
                          pixel_id: str = None) -> dict:
        """
        Create test ad sets for CPM optimization:
        1. Advantage+ Audience (US) - broader targeting
        2. UK Test - different geo with lower CPM

        Uses CAMPAIGN BUDGET (CBO) - no individual ad set budgets.
        Adds UTM parameters for full tracking.

        Args:
            campaign_id: Campaign to add ad sets to (must have CBO enabled)
            source_adset_id: Existing ad set to copy ads from
            pixel_id: Facebook Pixel ID for conversion tracking

        Returns:
            Results of ad set and ad creation
        """
        results = {
            "advantage_plus_adset": None,
            "uk_test_adset": None,
            "advantage_plus_ads": [],
            "uk_test_ads": [],
            "errors": []
        }

        # Get pixel ID from existing adset if not provided
        if not pixel_id:
            adset_details = self._request(f"/{source_adset_id}?fields=promoted_object")
            promoted_obj = adset_details.get("promoted_object", {})
            pixel_id = promoted_obj.get("pixel_id")

        promoted_object = {"pixel_id": pixel_id} if pixel_id else None

        # =====================================================
        # 1. Create Advantage+ Audience Ad Set (US, Broad)
        # =====================================================
        try:
            advantage_targeting = {
                "age_min": 21,
                "age_max": 60,  # Broad age range
                "genders": [1],  # Women
                "geo_locations": {
                    "countries": ["US"],
                    "location_types": ["home"]
                }
                # NO interest targeting - let Advantage+ find users
            }

            adset_result = self.create_adset_cbo(
                campaign_id=campaign_id,
                name="TEST - Advantage+ US Women 21-60",
                targeting=advantage_targeting,
                optimization_goal="OFFSITE_CONVERSIONS",
                status="PAUSED",  # Start paused for review
                advantage_audience=True,
                promoted_object=promoted_object,
                url_tags="utm_source=meta&utm_medium=paid&utm_campaign=mirai_quiz&utm_content=advplus_us"
            )
            results["advantage_plus_adset"] = adset_result

            if adset_result.get("success"):
                # Copy ads to new ad set
                ads_result = self.duplicate_ads_to_adset(
                    source_adset_id=source_adset_id,
                    target_adset_id=adset_result["id"],
                    name_suffix="(Adv+)",
                    status="ACTIVE"
                )
                results["advantage_plus_ads"] = ads_result

        except Exception as e:
            results["errors"].append(f"Advantage+ adset error: {str(e)}")

        # =====================================================
        # 2. Create UK Test Ad Set (Lower CPM geo)
        # =====================================================
        try:
            uk_targeting = {
                "age_min": 21,
                "age_max": 60,
                "genders": [1],  # Women
                "geo_locations": {
                    "countries": ["GB"],  # UK
                    "location_types": ["home"]
                }
                # NO interest targeting
            }

            uk_adset_result = self.create_adset_cbo(
                campaign_id=campaign_id,
                name="TEST - UK Women 21-60 Broad",
                targeting=uk_targeting,
                optimization_goal="OFFSITE_CONVERSIONS",
                status="PAUSED",
                advantage_audience=True,
                promoted_object=promoted_object,
                url_tags="utm_source=meta&utm_medium=paid&utm_campaign=mirai_quiz&utm_content=broad_uk"
            )
            results["uk_test_adset"] = uk_adset_result

            if uk_adset_result.get("success"):
                # Copy ads to new ad set
                uk_ads_result = self.duplicate_ads_to_adset(
                    source_adset_id=source_adset_id,
                    target_adset_id=uk_adset_result["id"],
                    name_suffix="(UK)",
                    status="ACTIVE"
                )
                results["uk_test_ads"] = uk_ads_result

        except Exception as e:
            results["errors"].append(f"UK adset error: {str(e)}")

        return results

    def create_adset_cbo(self, campaign_id: str, name: str,
                         targeting: dict, optimization_goal: str = "OFFSITE_CONVERSIONS",
                         billing_event: str = "IMPRESSIONS",
                         status: str = "PAUSED",
                         advantage_audience: bool = False,
                         promoted_object: dict = None,
                         url_tags: str = None) -> dict:
        """
        Create ad set for Campaign Budget Optimization (no ad set budget).
        Budget is controlled at campaign level.

        Args:
            campaign_id: Parent campaign ID (must have CBO enabled)
            name: Ad set name
            targeting: Targeting spec dict
            optimization_goal: OFFSITE_CONVERSIONS, LINK_CLICKS, etc.
            billing_event: IMPRESSIONS, LINK_CLICKS
            status: ACTIVE or PAUSED
            advantage_audience: Enable Advantage+ Audience
            promoted_object: Pixel/page info for conversion optimization
            url_tags: UTM parameters to append to all URLs

        Returns:
            {"id": "adset_id", "success": true} or error
        """
        import json
        data = {
            "campaign_id": campaign_id,
            "name": name,
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": json.dumps(targeting),
            "status": status
        }

        # NO daily_budget - uses Campaign Budget Optimization (CBO)

        # Enable Advantage+ Audience
        if advantage_audience:
            data["targeting_optimization_types"] = json.dumps(["expansion_all"])

        # Add promoted object for conversion campaigns
        if promoted_object:
            data["promoted_object"] = json.dumps(promoted_object)

        # Add UTM tracking
        if url_tags:
            data["destination_type"] = "WEBSITE"
            # URL tags are appended to all ad URLs automatically

        endpoint = f"/act_{self.ad_account_id}/adsets"
        result = self._request(endpoint, "POST", data)
        if "id" in result:
            result["success"] = True

            # Set URL tags on the ad set (separate call)
            if url_tags and result.get("id"):
                self._request(f"/{result['id']}", "POST", {"url_tags": url_tags})

        return result

    def get_targeting_interests(self, query: str, limit: int = 20) -> List[dict]:
        """
        Search for targeting interests by keyword

        Args:
            query: Search term (e.g., "skincare", "beauty")
            limit: Max results

        Returns:
            List of interests with id, name, audience_size
        """
        endpoint = f"/search?type=adinterest&q={query}&limit={limit}"
        result = self._request(endpoint)
        return result.get("data", [])

    def get_custom_audiences(self, limit: int = 50) -> List[dict]:
        """Get custom audiences (lookalikes, website visitors, etc.)"""
        fields = "id,name,subtype,approximate_count"
        endpoint = f"/act_{self.ad_account_id}/customaudiences?fields={fields}&limit={limit}"
        result = self._request(endpoint)
        return result.get("data", [])

    @staticmethod
    def build_targeting(
        age_min: int = 25,
        age_max: int = 45,
        genders: List[int] = None,
        countries: List[str] = None,
        interest_ids: List[str] = None,
        custom_audience_ids: List[str] = None,
        excluded_audience_ids: List[str] = None
    ) -> dict:
        """
        Build a targeting specification dict

        Args:
            age_min: Minimum age (default 25)
            age_max: Maximum age (default 45)
            genders: [1] for women, [2] for men, [1,2] for all
            countries: List of country codes ["US", "CA", "GB"]
            interest_ids: List of interest IDs from get_targeting_interests
            custom_audience_ids: List of custom audience IDs
            excluded_audience_ids: List of audience IDs to exclude

        Returns:
            Targeting specification dict for create_adset
        """
        targeting = {
            "age_min": age_min,
            "age_max": age_max,
            "geo_locations": {
                "countries": countries or ["US"],
                "location_types": ["home"]
            }
        }

        if genders:
            targeting["genders"] = genders

        if interest_ids:
            targeting["flexible_spec"] = [
                {"interests": [{"id": iid} for iid in interest_ids]}
            ]

        if custom_audience_ids:
            targeting["custom_audiences"] = [{"id": aid} for aid in custom_audience_ids]

        if excluded_audience_ids:
            targeting["excluded_custom_audiences"] = [{"id": aid} for aid in excluded_audience_ids]

        return targeting

    @staticmethod
    def build_skincare_targeting_preset() -> dict:
        """
        Pre-built targeting for Mirai Skin's typical audience:
        Women 21-45 in US interested in skincare/beauty
        """
        return MetaAdsClient.build_targeting(
            age_min=21,
            age_max=45,
            genders=[1],  # Women only
            countries=["US"],
            interest_ids=[
                "6003107902433",  # Beauty
                "6003139266461",  # Skin care
            ]
        )


class DecisionEngine:
    """
    AI Decision Engine for Meta Ads Optimization

    Analyzes performance data and generates optimization decisions
    based on configurable rules and thresholds.
    """

    def __init__(self, access_token: str, ad_account_id: str, config: EngineConfig = None):
        self.client = MetaAdsClient(access_token, ad_account_id)
        self.config = config or EngineConfig()
        self.decisions: List[Decision] = []
        self.alerts: List[Dict] = []

    def analyze_campaign(self, campaign_id: str = None,
                         date_range: str = "today") -> Dict[str, Any]:
        """
        Full campaign analysis with decisions

        Returns:
            Analysis report with metrics, decisions, and recommendations
        """
        self.decisions = []
        self.alerts = []

        report = {
            "timestamp": datetime.now().isoformat(),
            "date_range": date_range,
            "config": asdict(self.config),
            "account_summary": None,
            "campaigns": [],
            "decisions": [],
            "alerts": [],
            "recommendations": [],
            "health_score": 0
        }

        # Get account-level insights
        account_metrics = self.client.get_insights(None, "account", date_range)
        report["account_summary"] = asdict(account_metrics)

        # Analyze campaigns
        campaigns = self.client.get_campaigns()
        for campaign in campaigns:
            if campaign_id and campaign["id"] != campaign_id:
                continue
            if campaign.get("effective_status") != "ACTIVE":
                continue

            campaign_analysis = self._analyze_campaign_entity(campaign, date_range)
            report["campaigns"].append(campaign_analysis)

        # Compile decisions and recommendations
        report["decisions"] = [asdict(d) for d in self.decisions]
        report["alerts"] = self.alerts
        report["recommendations"] = self._generate_recommendations()
        report["health_score"] = self._calculate_health_score(account_metrics)

        return report

    def _analyze_campaign_entity(self, campaign: dict, date_range: str) -> dict:
        """Analyze a single campaign and its ad sets/ads"""
        campaign_metrics = self.client.get_insights(campaign["id"], "campaign", date_range)

        analysis = {
            "id": campaign["id"],
            "name": campaign["name"],
            "status": campaign.get("effective_status"),
            "metrics": asdict(campaign_metrics),
            "adsets": []
        }

        # Check campaign-level performance
        self._evaluate_entity(campaign, campaign_metrics, "campaign")

        # Analyze ad sets
        adsets = self.client.get_adsets(campaign["id"])
        for adset in adsets:
            if adset.get("effective_status") != "ACTIVE":
                continue
            adset_analysis = self._analyze_adset(adset, date_range)
            analysis["adsets"].append(adset_analysis)

        return analysis

    def _analyze_adset(self, adset: dict, date_range: str) -> dict:
        """Analyze ad set and its ads"""
        adset_metrics = self.client.get_insights(adset["id"], "adset", date_range)

        analysis = {
            "id": adset["id"],
            "name": adset["name"],
            "status": adset.get("effective_status"),
            "metrics": asdict(adset_metrics),
            "ads": []
        }

        # Check ad set performance
        self._evaluate_entity(adset, adset_metrics, "adset")

        # Analyze individual ads
        ads = self.client.get_ads(adset["id"])
        for ad in ads:
            if ad.get("effective_status") != "ACTIVE":
                continue
            ad_metrics = self.client.get_insights(ad["id"], "ad", date_range)
            analysis["ads"].append({
                "id": ad["id"],
                "name": ad["name"],
                "metrics": asdict(ad_metrics)
            })
            self._evaluate_entity(ad, ad_metrics, "ad")

        return analysis

    def _get_entity_age_hours(self, entity: dict) -> float:
        """Calculate entity age in hours"""
        created_time = entity.get("created_time") or entity.get("start_time")
        if not created_time:
            return 999  # Assume old if no date

        try:
            # Parse ISO format: 2024-01-15T10:30:00+0000
            created = datetime.fromisoformat(created_time.replace("+0000", "+00:00"))
            age = datetime.now(created.tzinfo) - created
            return age.total_seconds() / 3600
        except:
            return 999

    def _get_maturity_phase(self, age_hours: float) -> str:
        """Determine campaign maturity phase"""
        if age_hours < self.config.phase_new:
            return "NEW"
        elif age_hours < self.config.phase_learning:
            return "LEARNING"
        else:
            return "MATURE"

    def _evaluate_entity(self, entity: dict, metrics: PerformanceMetrics,
                         entity_type: str) -> None:
        """Evaluate performance and generate decisions"""
        entity_id = entity["id"]
        entity_name = entity["name"]

        # Calculate age and maturity phase
        age_hours = self._get_entity_age_hours(entity)
        maturity_phase = self._get_maturity_phase(age_hours)
        age_days = age_hours / 24

        # Check if in learning phase (impressions OR time based)
        if metrics.impressions < self.config.learning_phase_impressions or age_hours < self.config.learning_phase_hours:
            time_remaining = max(0, self.config.learning_phase_hours - age_hours)
            self.decisions.append(Decision(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                decision_type=DecisionType.LEARNING,
                priority=Priority.LOW,
                reason=f"Learning phase: {metrics.impressions} impressions, {age_days:.1f} days old ({maturity_phase})",
                metrics={
                    "impressions": metrics.impressions,
                    "spend": metrics.spend,
                    "age_hours": round(age_hours, 1),
                    "age_days": round(age_days, 1),
                    "maturity_phase": maturity_phase,
                    "time_remaining_hours": round(time_remaining, 1)
                },
                recommended_action=f"WAIT - {maturity_phase} phase, {time_remaining:.0f}h until decisions enabled",
                auto_execute=False
            ))
            return

        # Not enough data for reliable decisions
        if metrics.impressions < self.config.min_impressions:
            return

        # Check if campaign is too new for pause decisions
        can_pause = (
            age_hours >= self.config.min_hours_before_pause and
            metrics.spend >= self.config.min_spend_before_pause
        )

        # Evaluate CTR
        if metrics.ctr < self.config.min_ctr:
            if can_pause:
                self.decisions.append(Decision(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    decision_type=DecisionType.PAUSE,
                    priority=Priority.HIGH,
                    reason=f"CTR {metrics.ctr:.2f}% below minimum {self.config.min_ctr}% ({age_days:.1f} days, €{metrics.spend:.2f} spent)",
                    metrics={
                        "ctr": metrics.ctr, "clicks": metrics.clicks, "impressions": metrics.impressions,
                        "age_days": round(age_days, 1), "spend": metrics.spend, "maturity_phase": maturity_phase
                    },
                    recommended_action="PAUSE - Low engagement, sufficient data collected",
                    auto_execute=self.config.auto_pause_underperformers
                ))
            else:
                hours_until_decision = max(0, self.config.min_hours_before_pause - age_hours)
                spend_until_decision = max(0, self.config.min_spend_before_pause - metrics.spend)
                self.decisions.append(Decision(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    decision_type=DecisionType.ALERT,
                    priority=Priority.MEDIUM,
                    reason=f"CTR {metrics.ctr:.2f}% low, but campaign too new ({age_days:.1f} days, €{metrics.spend:.2f} spent)",
                    metrics={
                        "ctr": metrics.ctr, "clicks": metrics.clicks, "age_days": round(age_days, 1),
                        "spend": metrics.spend, "maturity_phase": maturity_phase,
                        "hours_until_decision": round(hours_until_decision, 1),
                        "spend_until_decision": round(spend_until_decision, 2)
                    },
                    recommended_action=f"MONITOR - Wait {hours_until_decision:.0f}h or €{spend_until_decision:.0f} more spend before pause decision",
                    auto_execute=False
                ))
        elif metrics.ctr >= self.config.excellent_ctr:
            self.decisions.append(Decision(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                decision_type=DecisionType.SCALE,
                priority=Priority.HIGH,
                reason=f"Excellent CTR {metrics.ctr:.2f}% (target: {self.config.target_ctr}%)",
                metrics={"ctr": metrics.ctr, "clicks": metrics.clicks, "spend": metrics.spend},
                recommended_action=f"SCALE - Increase budget by {self.config.scale_budget_increase*100:.0f}%",
                auto_execute=self.config.auto_scale_winners
            ))

        # Evaluate CPA (if we have conversions)
        if metrics.purchases > 0:
            cpa = metrics.cost_per_purchase

            if cpa > self.config.alert_cpa:
                self.alerts.append({
                    "type": "HIGH_CPA",
                    "severity": "CRITICAL" if can_pause else "WARNING",
                    "entity": entity_name,
                    "message": f"CPA €{cpa:.2f} exceeds alert threshold €{self.config.alert_cpa} ({age_days:.1f} days old)",
                    "metrics": {"cpa": cpa, "purchases": metrics.purchases, "spend": metrics.spend, "age_days": round(age_days, 1)}
                })
                if can_pause:
                    self.decisions.append(Decision(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        entity_name=entity_name,
                        decision_type=DecisionType.PAUSE,
                        priority=Priority.CRITICAL,
                        reason=f"CPA €{cpa:.2f} critically high ({age_days:.1f} days, sufficient data)",
                        metrics={"cpa": cpa, "purchases": metrics.purchases, "roas": metrics.roas, "age_days": round(age_days, 1), "maturity_phase": maturity_phase},
                        recommended_action="PAUSE - CPA too high, sufficient data collected",
                        auto_execute=self.config.auto_pause_underperformers
                    ))
                else:
                    self.decisions.append(Decision(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        entity_name=entity_name,
                        decision_type=DecisionType.ALERT,
                        priority=Priority.HIGH,
                        reason=f"CPA €{cpa:.2f} high, but campaign too new ({age_days:.1f} days)",
                        metrics={"cpa": cpa, "purchases": metrics.purchases, "age_days": round(age_days, 1), "maturity_phase": maturity_phase},
                        recommended_action=f"MONITOR - High CPA but in {maturity_phase} phase, wait for more data",
                        auto_execute=False
                    ))
            elif cpa > self.config.max_cpa:
                self.decisions.append(Decision(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    decision_type=DecisionType.ALERT,
                    priority=Priority.HIGH,
                    reason=f"CPA €{cpa:.2f} above maximum €{self.config.max_cpa}",
                    metrics={"cpa": cpa, "purchases": metrics.purchases},
                    recommended_action="REVIEW - Consider pausing or optimizing",
                    auto_execute=False
                ))
            elif cpa <= self.config.target_cpa and metrics.roas >= self.config.scale_min_roas:
                self.decisions.append(Decision(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    decision_type=DecisionType.SCALE,
                    priority=Priority.HIGH,
                    reason=f"CPA €{cpa:.2f} at/below target €{self.config.target_cpa}, ROAS {metrics.roas:.2f}x",
                    metrics={"cpa": cpa, "roas": metrics.roas, "purchases": metrics.purchases},
                    recommended_action=f"SCALE - Profitable! Increase budget",
                    auto_execute=self.config.auto_scale_winners
                ))

        # Evaluate CPC
        if metrics.cpc > self.config.max_cpc and metrics.clicks >= self.config.min_clicks:
            self.decisions.append(Decision(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                decision_type=DecisionType.ALERT,
                priority=Priority.MEDIUM,
                reason=f"CPC €{metrics.cpc:.2f} above maximum €{self.config.max_cpc}",
                metrics={"cpc": metrics.cpc, "clicks": metrics.clicks},
                recommended_action="REVIEW - High cost per click",
                auto_execute=False
            ))

        # Check frequency (ad fatigue)
        if metrics.frequency > 3.0:
            self.alerts.append({
                "type": "HIGH_FREQUENCY",
                "severity": "WARNING",
                "entity": entity_name,
                "message": f"Frequency {metrics.frequency:.1f} indicates potential ad fatigue",
                "metrics": {"frequency": metrics.frequency, "reach": metrics.reach}
            })

    def _generate_recommendations(self) -> List[Dict]:
        """Generate high-level recommendations based on all decisions"""
        recommendations = []

        # Count decision types
        scale_decisions = [d for d in self.decisions if d.decision_type == DecisionType.SCALE]
        pause_decisions = [d for d in self.decisions if d.decision_type == DecisionType.PAUSE]
        learning_decisions = [d for d in self.decisions if d.decision_type == DecisionType.LEARNING]

        if scale_decisions:
            recommendations.append({
                "priority": "HIGH",
                "type": "SCALE_WINNERS",
                "title": f"Scale {len(scale_decisions)} winning ad(s)",
                "description": "These ads are performing above targets. Consider increasing budget.",
                "entities": [d.entity_name for d in scale_decisions],
                "potential_impact": "Increase conversions while maintaining efficiency"
            })

        if pause_decisions:
            recommendations.append({
                "priority": "HIGH",
                "type": "PAUSE_UNDERPERFORMERS",
                "title": f"Pause {len(pause_decisions)} underperforming ad(s)",
                "description": "These ads are below performance thresholds. Pausing will save budget.",
                "entities": [d.entity_name for d in pause_decisions],
                "potential_impact": "Save budget for better performing ads"
            })

        if learning_decisions:
            recommendations.append({
                "priority": "LOW",
                "type": "WAIT_FOR_DATA",
                "title": f"{len(learning_decisions)} ad(s) still learning",
                "description": "These ads need more impressions before making optimization decisions.",
                "entities": [d.entity_name for d in learning_decisions],
                "potential_impact": "Allow 24-48 hours for sufficient data"
            })

        # Budget allocation recommendation
        if scale_decisions and pause_decisions:
            recommendations.append({
                "priority": "MEDIUM",
                "type": "REALLOCATE_BUDGET",
                "title": "Reallocate budget from losers to winners",
                "description": "Shift budget from underperforming ads to top performers.",
                "potential_impact": "Improve overall campaign efficiency"
            })

        return recommendations

    def _calculate_health_score(self, metrics: PerformanceMetrics) -> int:
        """Calculate overall campaign health score (0-100)"""
        score = 50  # Base score

        # CTR scoring (+/- 15 points)
        if metrics.ctr >= self.config.excellent_ctr:
            score += 15
        elif metrics.ctr >= self.config.target_ctr:
            score += 10
        elif metrics.ctr >= self.config.min_ctr:
            score += 5
        else:
            score -= 15

        # CPA scoring (+/- 20 points)
        if metrics.purchases > 0:
            cpa = metrics.cost_per_purchase
            if cpa <= self.config.target_cpa:
                score += 20
            elif cpa <= self.config.max_cpa:
                score += 10
            elif cpa <= self.config.alert_cpa:
                score -= 10
            else:
                score -= 20

        # ROAS scoring (+/- 15 points)
        if metrics.roas >= 3.0:
            score += 15
        elif metrics.roas >= 2.0:
            score += 10
        elif metrics.roas >= 1.0:
            score += 5
        elif metrics.roas > 0:
            score -= 10

        return max(0, min(100, score))

    def execute_decision(self, decision: Decision) -> Dict:
        """Execute a single decision"""
        result = {"decision_id": decision.entity_id, "success": False, "action": None}

        try:
            if decision.decision_type == DecisionType.PAUSE:
                self.client.update_status(decision.entity_id, "PAUSED")
                result["success"] = True
                result["action"] = "PAUSED"

            elif decision.decision_type == DecisionType.SCALE:
                # For scaling, we'd need to get current budget and increase it
                # This is a simplified version
                result["success"] = True
                result["action"] = "SCALE_RECOMMENDED"

        except Exception as e:
            result["error"] = str(e)

        return result

    def get_quick_status(self, date_range: str = "today") -> Dict:
        """Get quick campaign status overview"""
        metrics = self.client.get_insights(None, "account", date_range)

        return {
            "timestamp": datetime.now().isoformat(),
            "date_range": date_range,
            "spend": f"€{metrics.spend:.2f}",
            "impressions": metrics.impressions,
            "clicks": metrics.clicks,
            "ctr": f"{metrics.ctr:.2f}%",
            "cpc": f"€{metrics.cpc:.2f}",
            "quiz_completes": metrics.quiz_completes,
            "purchases": metrics.purchases,
            "cpa": f"€{metrics.cost_per_purchase:.2f}" if metrics.purchases > 0 else "N/A",
            "roas": f"{metrics.roas:.2f}x" if metrics.roas > 0 else "N/A",
            "health_score": self._calculate_health_score(metrics),
            "status": "HEALTHY" if self._calculate_health_score(metrics) >= 60 else "NEEDS_ATTENTION"
        }


# Factory function for easy instantiation
def create_engine(access_token: str = None, ad_account_id: str = None,
                  config: dict = None) -> DecisionEngine:
    """
    Create a DecisionEngine instance

    Args:
        access_token: Meta API access token (defaults to env var)
        ad_account_id: Ad account ID (defaults to env var)
        config: Optional configuration overrides
    """
    token = access_token or os.getenv("META_ACCESS_TOKEN")
    account = ad_account_id or os.getenv("META_AD_ACCOUNT_ID", "668790152408430")

    # Strip 'act_' prefix if present - the API client adds it
    if account.startswith("act_"):
        account = account[4:]

    engine_config = EngineConfig()
    if config:
        for key, value in config.items():
            if hasattr(engine_config, key):
                setattr(engine_config, key, value)

    return DecisionEngine(token, account, engine_config)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    # Load from environment
    access_token = os.getenv("META_ACCESS_TOKEN")
    ad_account_id = "668790152408430"

    if not access_token:
        print("ERROR: META_ACCESS_TOKEN environment variable not set")
        sys.exit(1)

    engine = create_engine(access_token, ad_account_id)

    print("=" * 60)
    print("MIRAI SKIN - META ADS DECISION ENGINE")
    print("=" * 60)

    # Quick status
    print("\n📊 QUICK STATUS (Today)")
    print("-" * 40)
    status = engine.get_quick_status("today")
    for key, value in status.items():
        if key != "timestamp":
            print(f"  {key}: {value}")

    # Full analysis
    print("\n🔍 FULL ANALYSIS")
    print("-" * 40)
    report = engine.analyze_campaign(date_range="today")

    print(f"\n  Health Score: {report['health_score']}/100")
    print(f"  Decisions: {len(report['decisions'])}")
    print(f"  Alerts: {len(report['alerts'])}")

    if report['recommendations']:
        print("\n📋 RECOMMENDATIONS:")
        for rec in report['recommendations']:
            print(f"  [{rec['priority']}] {rec['title']}")
            print(f"      {rec['description']}")

    if report['alerts']:
        print("\n⚠️  ALERTS:")
        for alert in report['alerts']:
            print(f"  [{alert['severity']}] {alert['message']}")
