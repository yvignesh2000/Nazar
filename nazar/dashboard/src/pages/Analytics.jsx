import { useState } from 'react';
import {
  BarChart3, TrendingUp, MessageSquare, Users, Brain,
  Target, Activity, Zap, IndianRupee, Trophy, Clock,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { useApi } from '../hooks/useApi';
import { analytics as analyticsApi, contacts as contactsApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Spinner from '../components/ui/Spinner';
import './Analytics.css';

const CHART_COLORS = {
  primary: '#6366f1',
  success: '#22c55e',
  warning: '#f59e0b',
  orange: '#f97316',
  danger: '#ef4444',
  gray: '#94a3b8',
  blue: '#3b82f6',
};

const PIPELINE_COLORS = [
  '#94a3b8', // New
  '#3b82f6', // Qualified
  '#6366f1', // Proposal
  '#f59e0b', // Negotiation
  '#22c55e', // Won
  '#ef4444', // Lost
];

function fmtINR(n) {
  if (n == null) return '₹0';
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${Number(n).toLocaleString('en-IN')}`;
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((entry, i) => (
        <div key={i} className="chart-tooltip-row">
          <span className="chart-tooltip-dot" style={{ background: entry.color }} />
          <span>{entry.name}: <strong>{entry.value?.toLocaleString()}</strong></span>
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const [trendDays, setTrendDays] = useState(14);
  const { data, loading } = useApi(() => analyticsApi.snapshot(), []);
  const { data: trendData } = useApi(() => analyticsApi.trend(trendDays), [trendDays]);
  const { data: aiData } = useApi(() => analyticsApi.ai(7), []);
  const { data: pipeData } = useApi(() => analyticsApi.pipeline(), []);
  const { data: leadData } = useApi(() => analyticsApi.leads(), []);
  const { data: contactsData } = useApi(() => contactsApi.list(), []);

  if (loading) return <Spinner />;

  const s = data || {};
  // Read both alias and legacy keys for safety
  const conv = s.conversations || s.conversation || {};
  const pipe = pipeData || s.pipeline || {};
  const ai = aiData || s.ai || s.ai_performance || {};
  const leads = leadData || s.leads || s.lead_quality || {};
  const trend = trendData?.trend || [];
  const allContacts = contactsData?.contacts || [];

  // Format trend data for recharts — accept both new aliases and legacy
  const chartTrend = trend.map(d => ({
    date: d.date?.slice(5) || '',
    Sent: d.messages_sent ?? d.ai_replies ?? 0,
    Received: d.messages_received ?? d.messages ?? 0,
  }));
  const trendHasData = chartTrend.some(d => d.Sent > 0 || d.Received > 0);

  // Pipeline data for pie chart
  const pipelineChartData = (pipe.stages || pipe.stage_distribution || [])
    .filter(s => (s.count || 0) > 0)
    .map((s, i) => ({
      name: s.stage,
      value: s.count,
      dealValue: s.total_value ?? s.value ?? 0,
      fill: PIPELINE_COLORS[i % PIPELINE_COLORS.length],
    }));

  // Lead score distribution for bar chart
  const leadChartData = (leads.score_distribution || []).map(b => ({
    range: b.range,
    count: b.count || 0,
  }));

  // Top open deals (Proposal + Negotiation, by value)
  const topOpenDeals = [...allContacts]
    .filter(c => ['Proposal', 'Negotiation', 'Qualified'].includes(c.pipeline_stage))
    .filter(c => (c.deal_value || 0) > 0)
    .sort((a, b) => (b.deal_value || 0) - (a.deal_value || 0))
    .slice(0, 5);

  // Pipeline value by stage (for the secondary insight)
  const valueByStage = (pipe.stages || pipe.stage_distribution || [])
    .filter(s => (s.total_value ?? s.value ?? 0) > 0)
    .map(s => ({
      stage: s.stage,
      value: s.total_value ?? s.value ?? 0,
      count: s.count,
    }));

  const totalSent = conv.total_sent ?? conv.total_outbound ?? 0;
  const totalReceived = conv.total_received ?? conv.total_inbound ?? 0;
  const aiReplies = ai.total_ai_replies ?? conv.ai_replies ?? 0;
  const handoffRate = ai.handoff_rate ?? conv.handoff_rate_pct ?? 0;
  const conversionRate = pipe.conversion_rate ?? pipe.win_rate_pct ?? 0;
  const activeLeads = pipe.active_leads ?? pipe.active ?? 0;
  const totalPipelineValue = pipe.total_pipeline_value ?? 0;
  const totalWonValue = pipe.total_won_value ?? 0;
  const avgDealValue = pipe.avg_deal_value ?? 0;
  const pipelineHealth = pipe.pipeline_health_score ?? 0;

  return (
    <div className="page-content">
      <PageHeader
        title="Reports"
        description="Track performance, conversions, and pipeline health"
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

      {/* Top stat cards — business KPIs first */}
      <div className="stat-grid">
        <StatCard
          icon={IndianRupee}
          label="Pipeline Value"
          value={fmtINR(totalPipelineValue)}
          variant="default"
        />
        <StatCard
          icon={Trophy}
          label="Closed Won"
          value={fmtINR(totalWonValue)}
          variant="success"
        />
        <StatCard
          icon={Target}
          label="Win Rate"
          value={`${Number(conversionRate).toFixed(1)}%`}
          variant="success"
        />
        <StatCard
          icon={Users}
          label="Active Leads"
          value={activeLeads}
          variant="warning"
        />
        <StatCard
          icon={IndianRupee}
          label="Avg Deal Size"
          value={fmtINR(avgDealValue)}
          variant="default"
        />
        <StatCard
          icon={Activity}
          label="Pipeline Health"
          value={`${pipelineHealth}/100`}
          variant={pipelineHealth >= 70 ? 'success' : pipelineHealth >= 40 ? 'warning' : 'orange'}
        />
      </div>

      {/* Conversation KPIs */}
      <div className="stat-grid stat-grid--secondary">
        <StatCard
          icon={MessageSquare}
          label="Messages Sent"
          value={Number(totalSent).toLocaleString()}
          variant="default"
        />
        <StatCard
          icon={MessageSquare}
          label="Messages Received"
          value={Number(totalReceived).toLocaleString()}
          variant="success"
        />
        <StatCard
          icon={Brain}
          label="AI Replies"
          value={Number(aiReplies).toLocaleString()}
          variant="default"
        />
        <StatCard
          icon={Zap}
          label="Handoff Rate"
          value={`${Number(handoffRate).toFixed(1)}%`}
          variant="orange"
        />
      </div>

      <div className="analytics-grid">
        {/* Message trend — Area Chart */}
        <div className="panel analytics-panel analytics-panel--wide">
          <h2 className="panel-title"><Activity size={16} /> Message Trend</h2>
          <div className="panel-body">
            {trendHasData ? (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartTrend} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradSent" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART_COLORS.primary} stopOpacity={0.25} />
                      <stop offset="95%" stopColor={CHART_COLORS.primary} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gradReceived" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART_COLORS.success} stopOpacity={0.25} />
                      <stop offset="95%" stopColor={CHART_COLORS.success} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-gray-100)" />
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="var(--color-gray-400)" />
                  <YAxis tick={{ fontSize: 12 }} stroke="var(--color-gray-400)" />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend iconType="circle" iconSize={8} />
                  <Area type="monotone" dataKey="Sent"     stroke={CHART_COLORS.primary} fill="url(#gradSent)"     strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="Received" stroke={CHART_COLORS.success} fill="url(#gradReceived)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="panel-empty">No conversation activity in this window.</p>
            )}
          </div>
        </div>

        {/* Pipeline — Pie Chart */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><TrendingUp size={16} /> Pipeline Distribution</h2>
          <div className="panel-body">
            {pipelineChartData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={pipelineChartData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                      {pipelineChartData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                    </Pie>
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="chart-tooltip">
                            <strong>{d.name}</strong>
                            <div>{d.value} contacts</div>
                            <div>{fmtINR(d.dealValue)}</div>
                          </div>
                        );
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pipe-legend">
                  {pipelineChartData.map((s, i) => (
                    <div key={i} className="pipe-legend-item">
                      <span className="pipe-legend-dot" style={{ background: s.fill }} />
                      <span>{s.name}</span>
                      <span className="pipe-legend-count">{s.value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="panel-empty">No pipeline data yet.</p>
            )}
          </div>
        </div>

        {/* Pipeline value by stage — horizontal bars */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><IndianRupee size={16} /> Pipeline Value by Stage</h2>
          <div className="panel-body">
            {valueByStage.length > 0 ? (
              <div className="value-stage-list">
                {valueByStage.map((s, i) => {
                  const max = Math.max(...valueByStage.map(x => x.value));
                  const pct = (s.value / max) * 100;
                  return (
                    <div key={i} className="value-stage-row">
                      <div className="value-stage-meta">
                        <span className="value-stage-name">{s.stage}</span>
                        <span className="value-stage-count">{s.count} {s.count === 1 ? 'deal' : 'deals'}</span>
                      </div>
                      <div className="value-stage-bar-wrap">
                        <div
                          className="value-stage-bar"
                          style={{ width: `${pct}%`, background: PIPELINE_COLORS[i % PIPELINE_COLORS.length] }}
                        />
                      </div>
                      <span className="value-stage-value">{fmtINR(s.value)}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="panel-empty">No deals with values yet.</p>
            )}
          </div>
        </div>

        {/* Top open deals */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><Trophy size={16} /> Top Open Deals</h2>
          <div className="panel-body">
            {topOpenDeals.length > 0 ? (
              <div className="top-deals-list">
                {topOpenDeals.map(c => (
                  <div key={c.contact_id} className="top-deal-row">
                    <div className="top-deal-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                    <div className="top-deal-info">
                      <div className="top-deal-name">{c.name || 'Unknown'}</div>
                      <div className="top-deal-meta">
                        <span>{c.company || '—'}</span>
                        <span className="top-deal-stage">{c.pipeline_stage}</span>
                      </div>
                    </div>
                    <div className="top-deal-value">{fmtINR(c.deal_value)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="panel-empty">No open deals to show.</p>
            )}
          </div>
        </div>

        {/* AI performance */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><Brain size={16} /> AI Performance</h2>
          <div className="panel-body">
            <div className="ai-stats-grid">
              <div className="ai-stat">
                <span className="ai-stat-value">{Number(aiReplies).toLocaleString()}</span>
                <span className="ai-stat-label">Total AI Replies</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value">{`${Number(handoffRate).toFixed(1)}%`}</span>
                <span className="ai-stat-label">Handoff Rate</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value">{ai.fallback_count ?? ai.fallback_events ?? 0}</span>
                <span className="ai-stat-label">LLM Fallbacks</span>
              </div>
              <div className="ai-stat">
                <span className="ai-stat-value"><Clock size={14} style={{verticalAlign:'-2px'}}/> {ai.avg_response_time || '< 3s'}</span>
                <span className="ai-stat-label">Avg Response</span>
              </div>
            </div>
          </div>
        </div>

        {/* Lead quality — Bar Chart */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><BarChart3 size={16} /> Lead Score Distribution</h2>
          <div className="panel-body">
            {leadChartData.some(d => d.count > 0) ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={leadChartData} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-gray-100)" />
                    <XAxis dataKey="range" tick={{ fontSize: 11 }} stroke="var(--color-gray-400)" />
                    <YAxis tick={{ fontSize: 11 }} stroke="var(--color-gray-400)" allowDecimals={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="count" name="Leads" fill={CHART_COLORS.primary} radius={[4, 4, 0, 0]} maxBarSize={48} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="lead-summary">
                  <span>Avg Score: <strong>{(leads.avg_score ?? leads.overall_avg_score ?? 0).toFixed?.(0) ?? Math.round(leads.avg_score ?? leads.overall_avg_score ?? 0)}</strong></span>
                  <span>Total Leads: <strong>{leads.total_leads ?? leads.total_contacts ?? 0}</strong></span>
                </div>
              </>
            ) : (
              <p className="panel-empty">No lead scores yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
