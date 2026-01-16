/**
 * Meta Ads API Service
 * Fetches campaign data and enables programmatic ad management
 */

const META_API_VERSION = 'v18.0';
const META_API_BASE = `https://graph.facebook.com/${META_API_VERSION}`;

class MetaAdsService {
  constructor(accessToken, adAccountId) {
    this.accessToken = accessToken;
    this.adAccountId = adAccountId;
  }

  async request(endpoint, method = 'GET', body = null) {
    const url = `${META_API_BASE}${endpoint}`;
    const options = {
      method,
      headers: {
        'Authorization': `Bearer ${this.accessToken}`,
        'Content-Type': 'application/json'
      }
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);
    const data = await response.json();

    if (data.error) {
      throw new Error(data.error.message);
    }

    return data;
  }

  // ========== READ OPERATIONS ==========

  async getCampaigns() {
    return this.request(
      `/act_${this.adAccountId}/campaigns?fields=id,name,status,objective,daily_budget,lifetime_budget`
    );
  }

  async getAdSets(campaignId = null) {
    const filter = campaignId ? `&filtering=[{"field":"campaign.id","operator":"EQUAL","value":"${campaignId}"}]` : '';
    return this.request(
      `/act_${this.adAccountId}/adsets?fields=id,name,status,daily_budget,targeting,optimization_goal${filter}`
    );
  }

  async getAds(adSetId = null) {
    const filter = adSetId ? `&filtering=[{"field":"adset.id","operator":"EQUAL","value":"${adSetId}"}]` : '';
    return this.request(
      `/act_${this.adAccountId}/ads?fields=id,name,status,creative,adset_id${filter}`
    );
  }

  async getInsights(objectId, level = 'account', dateRange = 'last_7d') {
    const datePreset = dateRange === 'today' ? 'today' :
                       dateRange === 'yesterday' ? 'yesterday' :
                       dateRange === 'last_7d' ? 'last_7d' : 'last_30d';

    const fields = [
      'impressions',
      'clicks',
      'spend',
      'ctr',
      'cpc',
      'cpm',
      'reach',
      'frequency',
      'actions',
      'cost_per_action_type'
    ].join(',');

    const endpoint = level === 'account'
      ? `/act_${this.adAccountId}/insights`
      : `/${objectId}/insights`;

    return this.request(
      `${endpoint}?fields=${fields}&date_preset=${datePreset}&level=${level}`
    );
  }

  async getAccountInsights(dateRange = 'today') {
    const insights = await this.getInsights(null, 'account', dateRange);
    return this.parseInsights(insights.data?.[0] || {});
  }

  async getCampaignInsights(campaignId, dateRange = 'today') {
    const insights = await this.getInsights(campaignId, 'campaign', dateRange);
    return this.parseInsights(insights.data?.[0] || {});
  }

  async getAdInsights(adId, dateRange = 'today') {
    const insights = await this.getInsights(adId, 'ad', dateRange);
    return this.parseInsights(insights.data?.[0] || {});
  }

  parseInsights(data) {
    const actions = data.actions || [];
    const costPerAction = data.cost_per_action_type || [];

    const getAction = (type) => {
      const action = actions.find(a => a.action_type === type);
      return action ? parseInt(action.value) : 0;
    };

    const getCostPerAction = (type) => {
      const cost = costPerAction.find(c => c.action_type === type);
      return cost ? parseFloat(cost.value) : 0;
    };

    return {
      impressions: parseInt(data.impressions || 0),
      clicks: parseInt(data.clicks || 0),
      spend: parseFloat(data.spend || 0),
      ctr: parseFloat(data.ctr || 0),
      cpc: parseFloat(data.cpc || 0),
      cpm: parseFloat(data.cpm || 0),
      reach: parseInt(data.reach || 0),
      frequency: parseFloat(data.frequency || 0),
      // Custom conversions
      quizStarts: getAction('offsite_conversion.custom.StartAnalysis'),
      quizCompletes: getAction('offsite_conversion.custom.CompleteAnalysis'),
      addToCarts: getAction('offsite_conversion.fb_pixel_add_to_cart'),
      purchases: getAction('offsite_conversion.fb_pixel_purchase'),
      // Cost per conversion
      costPerQuizComplete: getCostPerAction('offsite_conversion.custom.CompleteAnalysis'),
      costPerAddToCart: getCostPerAction('offsite_conversion.fb_pixel_add_to_cart'),
      costPerPurchase: getCostPerAction('offsite_conversion.fb_pixel_purchase')
    };
  }

  // ========== WRITE OPERATIONS ==========

  async updateAdStatus(adId, status) {
    // status: 'ACTIVE', 'PAUSED'
    return this.request(`/${adId}`, 'POST', { status });
  }

  async updateAdSetBudget(adSetId, dailyBudget) {
    // dailyBudget in cents (e.g., 2000 = $20)
    return this.request(`/${adSetId}`, 'POST', { daily_budget: dailyBudget });
  }

  async updateCampaignStatus(campaignId, status) {
    return this.request(`/${campaignId}`, 'POST', { status });
  }

  // ========== CREATE OPERATIONS ==========

  async createCampaign(name, objective = 'CONVERSIONS', dailyBudget = 2000, status = 'PAUSED') {
    return this.request(`/act_${this.adAccountId}/campaigns`, 'POST', {
      name,
      objective,
      status,
      special_ad_categories: []
    });
  }

  async createAdSet(campaignId, name, dailyBudget, targeting, optimizationGoal = 'OFFSITE_CONVERSIONS') {
    return this.request(`/act_${this.adAccountId}/adsets`, 'POST', {
      campaign_id: campaignId,
      name,
      daily_budget: dailyBudget,
      billing_event: 'IMPRESSIONS',
      optimization_goal: optimizationGoal,
      targeting,
      status: 'PAUSED'
    });
  }

  async uploadImage(imageUrl) {
    return this.request(`/act_${this.adAccountId}/adimages`, 'POST', {
      url: imageUrl
    });
  }

  async createAdCreative(name, imageHash, message, link, headline) {
    return this.request(`/act_${this.adAccountId}/adcreatives`, 'POST', {
      name,
      object_story_spec: {
        page_id: this.pageId,
        link_data: {
          image_hash: imageHash,
          link,
          message,
          name: headline,
          call_to_action: {
            type: 'LEARN_MORE',
            value: { link }
          }
        }
      }
    });
  }

  async createAd(adSetId, creativeId, name, status = 'PAUSED') {
    return this.request(`/act_${this.adAccountId}/ads`, 'POST', {
      adset_id: adSetId,
      creative: { creative_id: creativeId },
      name,
      status
    });
  }
}

export default MetaAdsService;
