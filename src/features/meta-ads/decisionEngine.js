/**
 * AI Decision Engine for Meta Ads Optimization
 * Analyzes performance and makes/executes optimization decisions
 */

class DecisionEngine {
  constructor(metaAdsService, config = {}) {
    this.meta = metaAdsService;

    // Configurable thresholds
    this.config = {
      // Performance thresholds
      minCTR: config.minCTR || 1.0,           // Pause ads below this CTR %
      targetCTR: config.targetCTR || 2.0,     // Scale ads above this CTR %
      maxCPA: config.maxCPA || 5.0,           // Alert if CPA exceeds this (EUR)
      minImpressions: config.minImpressions || 500, // Min impressions before decisions

      // Budget rules
      budgetIncreasePercent: config.budgetIncreasePercent || 20,
      budgetDecreasePercent: config.budgetDecreasePercent || 30,
      maxDailyBudget: config.maxDailyBudget || 5000, // cents (€50)
      minDailyBudget: config.minDailyBudget || 500,  // cents (€5)

      // Auto-actions enabled
      autoActions: config.autoActions || {
        pauseUnderperformers: false,
        scaleWinners: false,
        alertOnHighCPA: true
      },

      ...config
    };

    this.decisions = [];
    this.alerts = [];
  }

  /**
   * Analyze all ads and generate recommendations
   */
  async analyzePerformance() {
    this.decisions = [];
    this.alerts = [];

    try {
      // Get account-level insights
      const accountInsights = await this.meta.getAccountInsights('today');

      // Get all campaigns
      const campaigns = await this.meta.getCampaigns();

      // Analyze each campaign
      for (const campaign of campaigns.data || []) {
        if (campaign.status !== 'ACTIVE') continue;

        const campaignInsights = await this.meta.getCampaignInsights(campaign.id, 'today');
        await this.analyzeCampaign(campaign, campaignInsights);
      }

      // Generate summary
      return {
        timestamp: new Date().toISOString(),
        accountSummary: accountInsights,
        decisions: this.decisions,
        alerts: this.alerts,
        recommendations: this.generateRecommendations()
      };

    } catch (error) {
      console.error('Analysis error:', error);
      throw error;
    }
  }

  /**
   * Analyze a single campaign
   */
  async analyzeCampaign(campaign, insights) {
    // Get ad sets for this campaign
    const adSets = await this.meta.getAdSets(campaign.id);

    for (const adSet of adSets.data || []) {
      if (adSet.status !== 'ACTIVE') continue;

      // Get ads for this ad set
      const ads = await this.meta.getAds(adSet.id);

      for (const ad of ads.data || []) {
        if (ad.status !== 'ACTIVE') continue;

        const adInsights = await this.meta.getAdInsights(ad.id, 'today');
        this.analyzeAd(ad, adInsights, adSet, campaign);
      }
    }
  }

  /**
   * Analyze a single ad and generate decision
   */
  analyzeAd(ad, insights, adSet, campaign) {
    const { impressions, clicks, ctr, spend, costPerQuizComplete } = insights;

    // Skip if not enough data
    if (impressions < this.config.minImpressions) {
      this.decisions.push({
        adId: ad.id,
        adName: ad.name,
        type: 'LEARNING',
        reason: `Only ${impressions} impressions - needs ${this.config.minImpressions} for decisions`,
        action: 'WAIT',
        autoExecute: false
      });
      return;
    }

    // Check CTR performance
    if (ctr < this.config.minCTR) {
      this.decisions.push({
        adId: ad.id,
        adName: ad.name,
        type: 'UNDERPERFORMER',
        reason: `CTR ${ctr.toFixed(2)}% is below ${this.config.minCTR}% threshold`,
        action: 'PAUSE',
        metrics: { ctr, impressions, clicks, spend },
        autoExecute: this.config.autoActions.pauseUnderperformers
      });
    } else if (ctr >= this.config.targetCTR) {
      this.decisions.push({
        adId: ad.id,
        adName: ad.name,
        type: 'WINNER',
        reason: `CTR ${ctr.toFixed(2)}% exceeds ${this.config.targetCTR}% target`,
        action: 'SCALE',
        metrics: { ctr, impressions, clicks, spend },
        autoExecute: this.config.autoActions.scaleWinners
      });
    } else {
      this.decisions.push({
        adId: ad.id,
        adName: ad.name,
        type: 'ACCEPTABLE',
        reason: `CTR ${ctr.toFixed(2)}% is acceptable`,
        action: 'MAINTAIN',
        metrics: { ctr, impressions, clicks, spend },
        autoExecute: false
      });
    }

    // Check CPA
    if (costPerQuizComplete > 0 && costPerQuizComplete > this.config.maxCPA) {
      this.alerts.push({
        adId: ad.id,
        adName: ad.name,
        type: 'HIGH_CPA',
        message: `CPA €${costPerQuizComplete.toFixed(2)} exceeds €${this.config.maxCPA} limit`,
        severity: 'WARNING'
      });
    }
  }

  /**
   * Generate high-level recommendations
   */
  generateRecommendations() {
    const winners = this.decisions.filter(d => d.type === 'WINNER');
    const losers = this.decisions.filter(d => d.type === 'UNDERPERFORMER');
    const learning = this.decisions.filter(d => d.type === 'LEARNING');

    const recommendations = [];

    if (winners.length > 0) {
      recommendations.push({
        priority: 'HIGH',
        type: 'SCALE_WINNERS',
        message: `${winners.length} ad(s) performing above target. Consider increasing budget.`,
        ads: winners.map(w => w.adName)
      });
    }

    if (losers.length > 0) {
      recommendations.push({
        priority: 'HIGH',
        type: 'PAUSE_LOSERS',
        message: `${losers.length} ad(s) underperforming. Consider pausing to save budget.`,
        ads: losers.map(l => l.adName)
      });
    }

    if (learning.length > 0) {
      recommendations.push({
        priority: 'LOW',
        type: 'WAIT_FOR_DATA',
        message: `${learning.length} ad(s) still in learning phase. Wait for more impressions.`,
        ads: learning.map(l => l.adName)
      });
    }

    if (this.alerts.length > 0) {
      recommendations.push({
        priority: 'MEDIUM',
        type: 'CPA_ALERT',
        message: `${this.alerts.length} alert(s) for high cost per acquisition.`,
        alerts: this.alerts
      });
    }

    return recommendations;
  }

  /**
   * Execute approved decisions
   */
  async executeDecisions(approvedDecisionIds = []) {
    const results = [];

    for (const decision of this.decisions) {
      // Only execute if approved or auto-execute is enabled
      const shouldExecute = decision.autoExecute ||
                           approvedDecisionIds.includes(decision.adId);

      if (!shouldExecute) continue;

      try {
        switch (decision.action) {
          case 'PAUSE':
            await this.meta.updateAdStatus(decision.adId, 'PAUSED');
            results.push({ adId: decision.adId, action: 'PAUSED', success: true });
            break;

          case 'SCALE':
            // Increase ad set budget by configured percentage
            // Note: Need to get current budget first
            results.push({ adId: decision.adId, action: 'SCALE_REQUESTED', success: true });
            break;

          default:
            break;
        }
      } catch (error) {
        results.push({ adId: decision.adId, action: decision.action, success: false, error: error.message });
      }
    }

    return results;
  }

  /**
   * Update configuration
   */
  updateConfig(newConfig) {
    this.config = { ...this.config, ...newConfig };
  }
}

export default DecisionEngine;
