import { Users, MessageSquare, DollarSign, TrendingUp, HandMetal, CalendarClock } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { overview as overviewApi, handoffs as handoffApi, followups as followupApi, activity as activityApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Spinner from '../components/ui/Spinner';
import Badge from '../components/ui/Badge';
import { formatDistanceToNow } from 'date-fns';
import './Overview.css';

export default function Overview() {
  const { data, loading } = useApi(() => overviewApi.get(), []);
  const { data: handoffData } = useApi(() => handoffApi.stats(), []);
  const { data: followupData } = useApi(() => followupApi.list(), []);
  const { data: activityData } = useApi(() => activityApi.list(), []);

  if (loading) return <Spinner />;

  const o = data || {};
  const stats = o.stats || {};
  const recentContacts = o.recent_contacts || [];

  return (
    <div className="page-content">
      <PageHeader title="Overview" description="Your business at a glance" />

      <div className="stat-grid">
        <StatCard
          icon={Users}
          label="Total Contacts"
          value={stats.total_contacts || 0}
          variant="default"
        />
        <StatCard
          icon={MessageSquare}
          label="Active Leads"
          value={stats.active_leads || 0}
          variant="success"
        />
        <StatCard
          icon={DollarSign}
          label="Pipeline Value"
          value={`₹${(stats.pipeline_value || 0).toLocaleString('en-IN')}`}
          variant="warning"
        />
        <StatCard
          icon={TrendingUp}
          label="Revenue"
          value={`₹${(stats.total_revenue || 0).toLocaleString('en-IN')}`}
          variant="success"
        />
        <StatCard
          icon={HandMetal}
          label="In Handoff Queue"
          value={handoffData?.currently_in_queue || 0}
          variant="orange"
        />
        <StatCard
          icon={CalendarClock}
          label="Follow-ups Due"
          value={followupData?.followups?.length || 0}
          variant="warning"
        />
      </div>

      <div className="overview-panels">
        {/* Recent Activity */}
        <div className="panel">
          <h2 className="panel-title">Recent Activity</h2>
          <div className="panel-body">
            {(activityData?.activities || []).slice(0, 8).map((a, i) => (
              <div key={i} className="activity-item">
                <div className="activity-dot" />
                <div className="activity-text">
                  <span className="activity-name">{a.contact_name}</span>
                  <span className="activity-detail">{a.detail}</span>
                </div>
                <span className="activity-time">
                  {a.time ? formatDistanceToNow(new Date(a.time), { addSuffix: true }) : ''}
                </span>
              </div>
            ))}
            {(!activityData?.activities || activityData.activities.length === 0) && (
              <p className="panel-empty">No recent activity</p>
            )}
          </div>
        </div>

        {/* Recent Contacts */}
        <div className="panel">
          <h2 className="panel-title">Recent Contacts</h2>
          <div className="panel-body">
            {recentContacts.slice(0, 8).map(c => (
              <div key={c.contact_id} className="contact-row">
                <div className="contact-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                <div className="contact-info">
                  <span className="contact-name">{c.name || 'Unknown'}</span>
                  <span className="contact-phone">{c.phone}</span>
                </div>
                <Badge variant={c.stage === 'Won' ? 'success' : c.stage === 'Lost' ? 'danger' : 'default'}>
                  {c.stage}
                </Badge>
              </div>
            ))}
            {recentContacts.length === 0 && (
              <p className="panel-empty">No contacts yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
