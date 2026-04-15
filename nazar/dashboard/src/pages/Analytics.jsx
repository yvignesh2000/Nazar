import { useState } from 'react';
import {
  BarChart3, TrendingUp, MessageSquare, Users, Brain,
  Target, ArrowUpRight, ArrowDownRight, Activity, Zap,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { analytics as analyticsApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import './Analytics.css';

export default function Analytics() {
  const [trendDays, setTrendDays] = useState(14);
  const { data, loading } = useApi(() => analyticsApi.snapshot(), []);
  const { data: trendData } = useApi(() => analyticsApi.trend(trendDays), [trendDays]);
  const { data: aiData } = useApi(() => analyticsApi.ai(7), []);
  const { data: pipeData } = useApi(() => analyticsApi.pipeline(), []);
  const { data: leadData } = useApi(() => analyticsApi.leads(), []);

  if (loading) return <Spinner />;

  const s = data || {};
  const conv = s.conversations || {};
  const pipe = s.pipeline || {};
  const ai = aiData || {};
  const leads = leadData || {};
  const trend = trendData?.trend || [];
  const maxTrend = Math.max(1, ...trend.map(d => d.messages_sent || 0), ...trend.map(d => d.messages_received || 0));

  return (
    <div className="page-content">
      <PageHeader
        title="Analytics"
        description="Track performance, conversions, and ROI"
        actions={
          <select
            className="trend-select"
            value={trendDays}
            onChange={e => setTrendDays(Number(e.target.value))}
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        }
      />

      {/* Top stat cards */}
      <div className="stat-grid">
        <StatCard
          icon={MessageSquare}
          label="Messages Sent"
          value={conv.total_sent || 0}
          variant="default"
        />
        <StatCard
          icon={MessageSquare}
          label="Messages Received"
          value={conv.total_received || 0}
          variant="success"
        />
        <StatCard
          icon={Brain}
          label="AI Replies"
          value={ai.total_ai_replies || 0}
          variant="default"
        />
        <StatCard
          icon={Target}
          label="Conversion Rate"
          value={`${(pipe.conversion_rate || 0).toFixed(1)}%`}
          variant="success"
        />
        <StatCard
          icon={Users}
          label="Active Leads"
          value={pipe.active_leads || 0}
          variant="warning"
        />
        <StatCard
          icon={Zap}
          label="Handoff Rate"
          value={`${(ai.handoff_rate || 0).toFixed(1)}%`}
          variant="orange"
        />
      </div>

      <div className="analytics-grid">
        {/* Message trend chart */}
        <div className="panel analytics-panel analytics-panel--wide">
          <h2 className="panel-title"><Activity size={16} /> Message Trend</h2>
          <div className="panel-body trend-chart-wrap">
            {trend.length > 0 ? (
              <div className="trend-chart">
                {trend.map((d, i) => (
                  <div key={i} className="trend-bar-group">
                    <div className="trend-bars">
                      <div
                        className="trend-bar trend-bar--sent"
                        style={{ height: `${((d.messages_sent || 0) / maxTrend) * 100}%` }}
                        title={`Sent: ${d.messages_sent || 0}`}
                      />
                      <div
                        className="trend-bar trend-bar--received"
                        style={{ height: `${((d.messages_received || 0) / maxTrend) * 100}%` }}
                        title={`Received: ${d.messages_received || 0}`}
                      />
                    </div>
                    <span className="trend-label">{d.date?.slice(5) || ''}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="panel-empty">No trend data yet — send some messages first</p>
            )}
            <div className="trend-legend">
              <span className="trend-legend-item"><span className="trend-dot trend-dot--sent" /> Sent</span>
              <span className="trend-legend-item"><span className="trend-dot trend-dot--received" /> Received</span>
            </div>
          </div>
        </div>

        {/* Pipeline analytics */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><TrendingUp size={16} /> Pipeline</h2>
          <div className="panel-body">
            {(pipeData?.stages || []).map(stage => (
              <div key={stage.stage} className="pipe-row">
                <div className="pipe-info">
                  <span className="pipe-stage">{stage.stage}</span>
                  <span className="pipe-count">{stage.count} contacts</span>
                </div>
                <div className="pipe-bar-track">
                  <div
                    className="pipe-bar-fill"
                    style={{ width: `${Math.min(100, ((stage.count || 0) / Math.max(1, pipeData?.total_contacts || 1)) * 100)}%` }}
                  />
                </div>
                <span className="pipe-value">₹{(stage.total_value || 0).toLocaleString('en-IN')}</span>
              </div>
            ))}
            {(!pipeData?.stages || pipeData.stages.length === 0) && (
              <p className="panel-empty">No pipeline data</p>
            )}
          </div>
        </div>

        {/* AI performance */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><Brain size={16} /> AI Performance</h2>
          <div className="panel-body">
            <div className="ai-stats-grid">
              <div className="ai-stat">
                <span className="ai-stat-value">{ai.total_ai_replies || 0}</span>
                <span className="ai-stat-label">Total AI Replies</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value">{`${(ai.handoff_rate || 0).toFixed(1)}%`}</span>
                <span className="ai-stat-label">Handoff Rate</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value">{ai.fallback_count || 0}</span>
                <span className="ai-stat-label">Fallbacks</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value">{ai.avg_response_time || '—'}</span>
                <span className="ai-stat-label">Avg Response</span>
              </div>
            </div>
          </div>
        </div>

        {/* Lead quality */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><BarChart3 size={16} /> Lead Quality</h2>
          <div className="panel-body">
            {(leads.score_distribution || []).map(bucket => (
              <div key={bucket.range} className="lead-bucket">
                <span className="lead-range">{bucket.range}</span>
                <div className="lead-bar-track">
                  <div
                    className="lead-bar-fill"
                    style={{ width: `${Math.min(100, ((bucket.count || 0) / Math.max(1, leads.total_leads || 1)) * 100)}%` }}
                  />
                </div>
                <span className="lead-count">{bucket.count}</span>
              </div>
            ))}
            <div className="lead-summary">
              <span>Avg Score: <strong>{(leads.avg_score || 0).toFixed(0)}</strong></span>
              <span>Total Leads: <strong>{leads.total_leads || 0}</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
