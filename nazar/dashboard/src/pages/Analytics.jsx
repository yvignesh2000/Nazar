import { useState } from 'react';
import {
  BarChart3, TrendingUp, MessageSquare, Users, Brain,
  Target, ArrowUpRight, ArrowDownRight, Activity, Zap,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { useApi } from '../hooks/useApi';
import { analytics as analyticsApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Badge from '../components/ui/Badge';
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
  '#6366f1', '#3b82f6', '#22c55e', '#f59e0b', '#10b981', '#94a3b8',
];

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

  if (loading) return <Spinner />;

  const s = data || {};
  const conv = s.conversations || {};
  const pipe = s.pipeline || {};
  const ai = aiData || {};
  const leads = leadData || {};
  const trend = trendData?.trend || [];

  // Format trend data for recharts
  const chartTrend = trend.map(d => ({
    date: d.date?.slice(5) || '',
    Sent: d.messages_sent || 0,
    Received: d.messages_received || 0,
  }));

  // Pipeline data for pie chart
  const pipelineChartData = (pipeData?.stages || [])
    .filter(s => s.count > 0)
    .map((s, i) => ({
      name: s.stage,
      value: s.count,
      dealValue: s.total_value || 0,
      fill: PIPELINE_COLORS[i % PIPELINE_COLORS.length],
    }));

  // Lead score distribution for bar chart
  const leadChartData = (leads.score_distribution || []).map(b => ({
    range: b.range,
    count: b.count || 0,
  }));

  return (
    <div className="page-content">
      <PageHeader
        title="Reports"
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
        {/* Message trend — Area Chart */}
        <div className="panel analytics-panel analytics-panel--wide">
          <h2 className="panel-title"><Activity size={16} /> Message Trend</h2>
          <div className="panel-body">
            {chartTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartTrend} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradSent" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART_COLORS.primary} stopOpacity={0.2} />
                      <stop offset="95%" stopColor={CHART_COLORS.primary} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gradReceived" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART_COLORS.success} stopOpacity={0.2} />
                      <stop offset="95%" stopColor={CHART_COLORS.success} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-gray-100)" />
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="var(--color-gray-400)" />
                  <YAxis tick={{ fontSize: 12 }} stroke="var(--color-gray-400)" />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend iconType="circle" iconSize={8} />
                  <Area
                    type="monotone"
                    dataKey="Sent"
                    stroke={CHART_COLORS.primary}
                    fill="url(#gradSent)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="Received"
                    stroke={CHART_COLORS.success}
                    fill="url(#gradReceived)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="panel-empty">No trend data yet — send some messages first</p>
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
                    <Pie
                      data={pipelineChartData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {pipelineChartData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="chart-tooltip">
                            <strong>{d.name}</strong>
                            <div>{d.value} contacts</div>
                            <div>₹{d.dealValue?.toLocaleString('en-IN')}</div>
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

        {/* Lead quality — Bar Chart */}
        <div className="panel analytics-panel">
          <h2 className="panel-title"><BarChart3 size={16} /> Lead Score Distribution</h2>
          <div className="panel-body">
            {leadChartData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={leadChartData} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-gray-100)" />
                    <XAxis dataKey="range" tick={{ fontSize: 11 }} stroke="var(--color-gray-400)" />
                    <YAxis tick={{ fontSize: 11 }} stroke="var(--color-gray-400)" />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar
                      dataKey="count"
                      name="Leads"
                      fill={CHART_COLORS.primary}
                      radius={[4, 4, 0, 0]}
                      maxBarSize={40}
                    />
                  </BarChart>
                </ResponsiveContainer>
                <div className="lead-summary">
                  <span>Avg Score: <strong>{(leads.avg_score || 0).toFixed(0)}</strong></span>
                  <span>Total Leads: <strong>{leads.total_leads || 0}</strong></span>
                </div>
              </>
            ) : (
              <p className="panel-empty">No lead data yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
