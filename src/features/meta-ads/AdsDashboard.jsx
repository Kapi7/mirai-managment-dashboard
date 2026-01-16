/**
 * Mirai Skin - Ads Performance Dashboard
 * Real-time Meta Ads monitoring with AI optimization
 */

import React, { useState, useEffect } from 'react';
import MetaAdsService from './metaAdsService';
import DecisionEngine from './decisionEngine';

// Configuration - Replace with your values
const CONFIG = {
  accessToken: process.env.NEXT_PUBLIC_META_ACCESS_TOKEN || '',
  adAccountId: process.env.NEXT_PUBLIC_META_AD_ACCOUNT_ID || '',
  refreshInterval: 300000 // 5 minutes
};

const AdsDashboard = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [insights, setInsights] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Decision engine config
  const [engineConfig, setEngineConfig] = useState({
    minCTR: 1.0,
    targetCTR: 2.0,
    maxCPA: 5.0,
    autoActions: {
      pauseUnderperformers: false,
      scaleWinners: false,
      alertOnHighCPA: true
    }
  });

  const fetchData = async () => {
    if (!CONFIG.accessToken || !CONFIG.adAccountId) {
      setError('Meta API credentials not configured');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);

      const metaService = new MetaAdsService(CONFIG.accessToken, CONFIG.adAccountId);
      const engine = new DecisionEngine(metaService, engineConfig);

      // Get account insights
      const accountInsights = await metaService.getAccountInsights('today');
      setInsights(accountInsights);

      // Run analysis
      const analysis = await engine.analyzePerformance();
      setDecisions(analysis.decisions);
      setRecommendations(analysis.recommendations);
      setLastUpdated(new Date());
      setError(null);

    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, CONFIG.refreshInterval);
    return () => clearInterval(interval);
  }, [engineConfig]);

  const executeDecision = async (decision) => {
    // TODO: Implement decision execution
    console.log('Executing decision:', decision);
  };

  if (loading && !insights) {
    return (
      <div className="ads-dashboard ads-dashboard--loading">
        <div className="loading-spinner" />
        <p>Loading campaign data...</p>
      </div>
    );
  }

  return (
    <div className="ads-dashboard">
      {/* Header */}
      <header className="ads-dashboard__header">
        <h1>📊 Ads Performance</h1>
        <div className="header-meta">
          {lastUpdated && (
            <span className="last-updated">
              Updated: {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button onClick={fetchData} className="refresh-btn">
            🔄 Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          ⚠️ {error}
        </div>
      )}

      {/* Performance Summary */}
      {insights && (
        <section className="performance-summary">
          <h2>Today's Performance</h2>
          <div className="metrics-grid">
            <MetricCard
              label="Spend"
              value={`€${insights.spend.toFixed(2)}`}
              subtitle="of €20 daily budget"
            />
            <MetricCard
              label="Impressions"
              value={insights.impressions.toLocaleString()}
              subtitle={`${insights.reach.toLocaleString()} reach`}
            />
            <MetricCard
              label="Clicks"
              value={insights.clicks}
              subtitle={`${insights.ctr.toFixed(2)}% CTR`}
              highlight={insights.ctr >= 2}
              warning={insights.ctr < 1}
            />
            <MetricCard
              label="Quiz Completes"
              value={insights.quizCompletes}
              subtitle={insights.costPerQuizComplete > 0
                ? `€${insights.costPerQuizComplete.toFixed(2)} each`
                : 'No conversions yet'}
              highlight={insights.costPerQuizComplete > 0 && insights.costPerQuizComplete < 3}
              warning={insights.costPerQuizComplete > 5}
            />
          </div>
        </section>
      )}

      {/* AI Recommendations */}
      {recommendations.length > 0 && (
        <section className="recommendations">
          <h2>🤖 AI Recommendations</h2>
          <div className="recommendations-list">
            {recommendations.map((rec, idx) => (
              <RecommendationCard key={idx} recommendation={rec} />
            ))}
          </div>
        </section>
      )}

      {/* Ad Decisions */}
      {decisions.length > 0 && (
        <section className="decisions">
          <h2>📋 Ad Performance</h2>
          <div className="decisions-table">
            <table>
              <thead>
                <tr>
                  <th>Ad</th>
                  <th>Status</th>
                  <th>CTR</th>
                  <th>Spend</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((decision, idx) => (
                  <tr key={idx} className={`decision-row decision-row--${decision.type.toLowerCase()}`}>
                    <td>{decision.adName}</td>
                    <td>
                      <StatusBadge type={decision.type} />
                    </td>
                    <td>{decision.metrics?.ctr?.toFixed(2) || '-'}%</td>
                    <td>€{decision.metrics?.spend?.toFixed(2) || '0.00'}</td>
                    <td>
                      {decision.action !== 'WAIT' && decision.action !== 'MAINTAIN' && (
                        <button
                          className={`action-btn action-btn--${decision.action.toLowerCase()}`}
                          onClick={() => executeDecision(decision)}
                        >
                          {decision.action}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Settings */}
      <section className="settings">
        <h2>⚙️ Auto-Optimization Rules</h2>
        <div className="settings-grid">
          <div className="setting-item">
            <label>
              <input
                type="checkbox"
                checked={engineConfig.autoActions.pauseUnderperformers}
                onChange={(e) => setEngineConfig({
                  ...engineConfig,
                  autoActions: {
                    ...engineConfig.autoActions,
                    pauseUnderperformers: e.target.checked
                  }
                })}
              />
              Auto-pause ads with CTR &lt; {engineConfig.minCTR}%
            </label>
          </div>
          <div className="setting-item">
            <label>
              <input
                type="checkbox"
                checked={engineConfig.autoActions.scaleWinners}
                onChange={(e) => setEngineConfig({
                  ...engineConfig,
                  autoActions: {
                    ...engineConfig.autoActions,
                    scaleWinners: e.target.checked
                  }
                })}
              />
              Auto-scale ads with CTR &gt; {engineConfig.targetCTR}%
            </label>
          </div>
          <div className="setting-item">
            <label>
              <input
                type="checkbox"
                checked={engineConfig.autoActions.alertOnHighCPA}
                onChange={(e) => setEngineConfig({
                  ...engineConfig,
                  autoActions: {
                    ...engineConfig.autoActions,
                    alertOnHighCPA: e.target.checked
                  }
                })}
              />
              Alert when CPA exceeds €{engineConfig.maxCPA}
            </label>
          </div>
        </div>
      </section>

      <style jsx>{`
        .ads-dashboard {
          padding: 24px;
          max-width: 1200px;
          margin: 0 auto;
          font-family: system-ui, -apple-system, sans-serif;
        }

        .ads-dashboard__header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
        }

        .ads-dashboard__header h1 {
          font-size: 24px;
          margin: 0;
        }

        .header-meta {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .last-updated {
          color: #666;
          font-size: 14px;
        }

        .refresh-btn {
          padding: 8px 16px;
          border: 1px solid #d4a5a5;
          background: white;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .refresh-btn:hover {
          background: #d4a5a5;
          color: white;
        }

        .error-banner {
          background: #fee2e2;
          color: #dc2626;
          padding: 12px 16px;
          border-radius: 8px;
          margin-bottom: 24px;
        }

        section {
          background: white;
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        section h2 {
          font-size: 18px;
          margin: 0 0 16px 0;
          color: #1a1a1a;
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
        }

        .recommendations-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .decisions-table {
          overflow-x: auto;
        }

        table {
          width: 100%;
          border-collapse: collapse;
        }

        th, td {
          text-align: left;
          padding: 12px;
          border-bottom: 1px solid #eee;
        }

        th {
          font-weight: 600;
          color: #666;
          font-size: 14px;
        }

        .decision-row--winner {
          background: #f0fdf4;
        }

        .decision-row--underperformer {
          background: #fef2f2;
        }

        .action-btn {
          padding: 6px 12px;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          font-size: 12px;
          font-weight: 600;
        }

        .action-btn--pause {
          background: #fee2e2;
          color: #dc2626;
        }

        .action-btn--scale {
          background: #dcfce7;
          color: #16a34a;
        }

        .settings-grid {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .setting-item label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
        }

        .ads-dashboard--loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 400px;
        }

        .loading-spinner {
          width: 40px;
          height: 40px;
          border: 3px solid #f3f3f3;
          border-top: 3px solid #d4a5a5;
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

// Sub-components
const MetricCard = ({ label, value, subtitle, highlight, warning }) => (
  <div className={`metric-card ${highlight ? 'highlight' : ''} ${warning ? 'warning' : ''}`}>
    <div className="metric-label">{label}</div>
    <div className="metric-value">{value}</div>
    <div className="metric-subtitle">{subtitle}</div>
    <style jsx>{`
      .metric-card {
        background: #f9fafb;
        padding: 16px;
        border-radius: 8px;
      }
      .metric-card.highlight {
        background: #f0fdf4;
        border: 1px solid #86efac;
      }
      .metric-card.warning {
        background: #fef2f2;
        border: 1px solid #fca5a5;
      }
      .metric-label {
        font-size: 14px;
        color: #666;
        margin-bottom: 4px;
      }
      .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #1a1a1a;
      }
      .metric-subtitle {
        font-size: 13px;
        color: #888;
        margin-top: 4px;
      }
    `}</style>
  </div>
);

const StatusBadge = ({ type }) => {
  const colors = {
    WINNER: { bg: '#dcfce7', text: '#16a34a' },
    UNDERPERFORMER: { bg: '#fee2e2', text: '#dc2626' },
    LEARNING: { bg: '#fef3c7', text: '#d97706' },
    ACCEPTABLE: { bg: '#e0f2fe', text: '#0284c7' }
  };
  const { bg, text } = colors[type] || colors.ACCEPTABLE;

  return (
    <span style={{
      background: bg,
      color: text,
      padding: '4px 8px',
      borderRadius: '4px',
      fontSize: '12px',
      fontWeight: 600
    }}>
      {type}
    </span>
  );
};

const RecommendationCard = ({ recommendation }) => {
  const icons = {
    SCALE_WINNERS: '🚀',
    PAUSE_LOSERS: '⏸️',
    WAIT_FOR_DATA: '⏳',
    CPA_ALERT: '⚠️'
  };

  const priorityColors = {
    HIGH: '#dc2626',
    MEDIUM: '#d97706',
    LOW: '#666'
  };

  return (
    <div className="recommendation-card">
      <span className="icon">{icons[recommendation.type] || '💡'}</span>
      <div className="content">
        <p className="message">{recommendation.message}</p>
        {recommendation.ads && (
          <p className="ads">Ads: {recommendation.ads.join(', ')}</p>
        )}
      </div>
      <span className="priority" style={{ color: priorityColors[recommendation.priority] }}>
        {recommendation.priority}
      </span>
      <style jsx>{`
        .recommendation-card {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 12px;
          background: #f9fafb;
          border-radius: 8px;
        }
        .icon {
          font-size: 20px;
        }
        .content {
          flex: 1;
        }
        .message {
          margin: 0;
          font-weight: 500;
        }
        .ads {
          margin: 4px 0 0;
          font-size: 13px;
          color: #666;
        }
        .priority {
          font-size: 12px;
          font-weight: 600;
        }
      `}</style>
    </div>
  );
};

export default AdsDashboard;
