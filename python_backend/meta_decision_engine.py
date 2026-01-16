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
    target_cpa: float = 25.00  # Target CPA
    max_cpa: float = 32.00
    alert_cpa: float = 40.00

    # CTR thresholds
    min_ctr: float = 0.8
    target_ctr: float = 1.5
    excellent_ctr: float = 2.5

    # CPC thresholds (EUR)
    target_cpc: float = 0.40
    max_cpc: float = 0.60

    # Minimum data for decisions
    min_impressions: int = 1000
    min_clicks: int = 50
    min_spend: float = 10.0

    # Learning phase - TIME BASED PROTECTION
    learning_phase_impressions: int = 500
    learning_phase_hours: int = 48  # Minimum 48 hours before kill decisions
    min_hours_before_pause: int = 72  # 3 days minimum before pausing
    min_spend_before_pause: float = 30.0  # Minimum €30 spent before pause decision

    # Campaign maturity phases (hours)
    phase_new: int = 48  # 0-48 hours = NEW (protected)
    phase_learning: int = 168  # 48-168 hours (7 days) = LEARNING
    # After 168 hours = MATURE (full optimization)

    # Budget rules
    scale_budget_increase: float = 0.20  # 20% increase
    scale_min_roas: float = 2.0

    # Auto-actions
    auto_pause_underperformers: bool = False
    auto_scale_winners: bool = False

    # Funnel conversion targets
    click_to_quiz_rate: float = 0.30  # 30% of clicks start quiz
    quiz_complete_rate: float = 0.60  # 60% complete quiz
    quiz_to_atc_rate: float = 0.15  # 15% add to cart
    atc_to_purchase_rate: float = 0.40  # 40% purchase


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
                    status: str = "PAUSED") -> dict:
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
